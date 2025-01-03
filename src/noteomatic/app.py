import base64
import hashlib
import logging
import os
import subprocess
import tempfile
import traceback
from typing import List, Optional
import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # Allow OAuth without HTTPS in development
from datetime import datetime
from pathlib import Path
from typing import List

import bs4
import graphviz
from bs4 import BeautifulSoup, Tag
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from flask import flash

from noteomatic.auth import User
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from googleapiclient.http import MediaIoBaseDownload

from noteomatic.config import settings
from noteomatic.database import NoteModel, get_repo
from noteomatic.lib import get_google_drive_service, submit_files
from noteomatic.llm import ai_search

# Cache for database connection
_db_connection = None


def _get_note_hash(title: str) -> str:
    """Generate a consistent hash for note sharing"""
    return hashlib.md5(title.encode()).hexdigest()[:8]


def get_note_by_id(note_id: int, user_id: str) -> NoteModel:
    """Get a note by its ID"""
    with get_repo(user_id) as repo:
        note = repo.get_by_id(note_id)
        if not note:
            raise KeyError(f"Note with ID {note_id} not found")
        return note

def get_all_notes(user_id: str) -> List[NoteModel]:
    """Get all notes from the database"""
    logging.info(f"Getting all notes for user {user_id}")
    
    # Load notes from user's directory if they exist
    user_notes_dir = settings.notes_dir / user_id
    logging.info(f"Checking user notes directory: {user_notes_dir}")
    
    if user_notes_dir.exists():
        logging.info(f"Found user notes directory, loading notes from {user_notes_dir}")
        load_notes_from_dir(user_notes_dir, user_id)
    else:
        logging.warning(f"User notes directory does not exist: {user_notes_dir}")
        
    with get_repo(user_id) as repo:
        notes = repo.get_all()
        for note in notes:
            # Parse content and get first two paragraphs
            soup = BeautifulSoup(note.raw_content, "html.parser")
            preview_paras = []
            for p in soup.find_all(['p', 'div']):
                if p.get_text().strip():  # Only include non-empty paragraphs
                    preview_paras.append(p.get_text().strip())
                    if len(preview_paras) == 2:
                        break
            note.preview_text = '\n'.join(preview_paras) if preview_paras else ''
        return notes

def count_notes() -> int:
    """Count the number of notes in the database"""
    with get_repo() as repo:
        return repo.count()


def load_notes_from_dir(dir: Path, user_id: Optional[str] = None) -> List[NoteModel]:
    """Load all notes from a directory into the database"""
    # Extract user_id from directory path if not provided
    if user_id is None:
        # Handle both possible directory structures:
        # 1. build/notes/users/$UID/
        # 2. build/notes/$UID/
        try:
            # Try the direct notes/$UID structure first
            user_id = dir.relative_to(settings.notes_dir).parts[0]
        except ValueError:
            # If that fails, try the notes/users/$UID structure
            try:
                user_id = dir.relative_to(settings.users_dir).parts[0]
            except ValueError:
                raise ValueError(f"Could not extract user ID from directory path: {dir}")
    
    logging.info(f"Loading notes from directory {dir} for user {user_id}")
    notes = []
    with get_repo(user_id) as repo:
        for dirpath, dirnames, filenames in os.walk(dir):
            logging.debug(f"Scanning directory: {dirpath}")
            logging.debug(f"Found files: {filenames}")
            
            for filename in filenames:
                file = Path(dirpath) / filename
                if file.is_dir() or file.suffix != ".html":
                    logging.debug(f"Skipping non-HTML file: {file}")
                    continue
                
                logging.info(f"Processing note file: {file}")

                try:
                    content, note = NoteModel.from_file(file, dir, user_id)
                    logging.info(f"Created note model from file: {note.title}")
                    
                    # Create or update the note, ensuring user_id is set
                    note = repo.create(
                        title=note.title,
                        path=str(file.relative_to(dir)),
                        content=content,
                        tags=note.tags,
                        created_at=note.created_at or datetime.now(),
                        user_id=user_id  # Explicitly pass user_id
                    )
                    logging.info(f"Saved note to database: {note.title}")
                    notes.append(note)
                except Exception as e:
                    logging.error(f"Error processing note file {file}: {str(e)}")
    return notes

NOTES_DIR = settings.notes_dir

app = Flask(
    __name__,
    static_url_path="/static",
    static_folder=str(settings.static_dir),
    template_folder=str(settings.template_dir),
)
app.secret_key = settings.secret_key

# Setup login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    """Load user from session"""
    from noteomatic.auth import User
    from flask import session
    
    user_data = session.get('user_data')
    if not user_data:
        return None
        
    return User.from_dict(user_data)

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


def _init():
    """Initialize database by loading notes from all user directories"""
    logging.info(f"Initializing database from {settings.users_dir}")
    
    # Ensure directories exist
    settings.users_dir.mkdir(parents=True, exist_ok=True)
    settings.notes_dir.mkdir(parents=True, exist_ok=True)
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    settings.build_dir.mkdir(parents=True, exist_ok=True)
    
    logging.info("Checking directory structure:")
    logging.info(f"- Users dir: {settings.users_dir} (exists: {settings.users_dir.exists()})")
    logging.info(f"- Notes dir: {settings.notes_dir} (exists: {settings.notes_dir.exists()})")
    
    # Initialize database tables
    from noteomatic.database import Base, connection
    Base.metadata.create_all(connection.engine)
    
    # Load notes for each user directory
    if settings.users_dir.exists():
        user_dirs = list(settings.users_dir.iterdir())
        logging.info(f"Found {len(user_dirs)} user directories")
        
        for user_dir in user_dirs:
            if user_dir.is_dir():
                user_id = user_dir.name
                user_notes_dir = settings.notes_dir / user_id
                logging.info(f"Processing user {user_id}:")
                logging.info(f"- User dir: {user_dir} (exists: {user_dir.exists()})")
                logging.info(f"- Notes dir: {user_notes_dir} (exists: {user_notes_dir.exists()})")
                
                if user_notes_dir.exists():
                    note_files = list(user_notes_dir.glob("**/*.html"))
                    logging.info(f"- Found {len(note_files)} note files")
                    load_notes_from_dir(user_notes_dir, user_id)
                else:
                    logging.warning(f"Notes directory missing for user {user_id}")
    else:
        logging.warning("Users directory does not exist yet")


_init()

@app.route("/search")
def search():
    """Search notes using FTS or AI"""
    query = request.args.get("q")
    mode = request.args.get("mode", "regular")
    
    if not query:
        return render_template("search.html", error="No query provided")

    if mode == "ai":
        # Get all notes for AI search, restricted to current user
        with get_repo(current_user.id) as repo:
            notes = repo.get_all()
            
        # Prepare notes with their IDs and content
        note_data = [(note.id, note.raw_content) for note in notes]
        
        # Get AI response
        cache_dir = settings.build_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        ai_response = ai_search(query, note_data, cache_dir)
        
        return render_template(
            "search.html",
            query=query,
            ai_mode=True,
            ai_response=ai_response
        )
    else:
        # Regular search
        with get_repo() as repo:
            search_results = repo.search(query)

        # Extract snippets
        for note in search_results:
            content = note.raw_content
            soup = BeautifulSoup(content, "html.parser")

            # Find the first paragraph that contains the query
            for p in soup.find_all("p"):
                if query.lower() in p.text.lower():
                    note.snippet = str(p)
                    break
            else:
                # If not found in paragraphs, try other elements
                snippet = soup.find(["p", "div"])
                if snippet:
                    note.snippet = str(snippet)

        return render_template(
            "search.html",
            query=query,
            results=search_results,
            ai_mode=False
        )


@app.route("/browse")
@login_required
def browse():
    """List all available notes"""
    notes = get_all_notes(current_user.id)
    return render_template("index.html", notes=notes, show_search=True)

@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    """Show upload and AI chat interface"""
    if request.method == "POST":
        message = request.json.get("message")
        if not message:
            return jsonify({"error": "No message provided"}), 400
            
        # Get all notes for AI search, restricted to current user
        with get_repo(current_user.id) as repo:
            notes = repo.get_all()
            
        # Prepare notes with their IDs and content
        note_data = [(note.id, note.raw_content) for note in notes]
        
        # Get AI response
        cache_dir = settings.build_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        ai_response = ai_search(message, note_data, cache_dir)
        
        return jsonify({
            "success": True,
            "response": ai_response
        })
        
    with get_repo(current_user.id) as repo:
        note_count = repo.count()
    return render_template("upload.html", note_count=note_count)


@app.route("/note/<int:note_id>", methods=["GET"])
@login_required
def show_note(note_id):
    """Display a specific note"""
    note = get_note_by_id(note_id, current_user.id)
    if not note:
        abort(404, "Note not found")

    # Process any graph tags
    soup = bs4.BeautifulSoup(note.raw_content, "html.parser")
    for graph_tag in soup.find_all("graph"):
        # Create an img tag to replace the graph
        img = soup.new_tag("img")
        graph_content = graph_tag.string or ""
        img["src"] = (
            f"/graph?dot={base64.urlsafe_b64encode(graph_content.encode()).decode()}"
        )
        img["class"] = "graph"
        img["style"] = "max-width: 100%; height: auto;"
        graph_tag.replace_with(img)

    # convert <sidenote> to <span class="sidenote">
    for sidenote_tag in soup.find_all("sidenote"):
        sidenote_tag.name = "span"
        sidenote_tag["class"] = "sidenote"

    # convert <link> to links to the tag page
    for link_tag in soup.find_all("wiki"):
        link_tag.name = "a"
        link_tag["href"] = url_for("show_tag", tag=link_tag.string)
        link_tag["class"] = "tag-link"

        # put text in the body of the link
        # link_tag.string.wrap(soup.new_tag("span"))

    # compute prev_url and next_url
    note_index = int(note.id)
    note_count = count_notes()
    prev_url = None
    next_url = None

    if note_index > 0:
        prev_url = f"/note/{note_index - 1}"
    if note_index < note_count - 1:
        next_url = f"/note/{note_index + 1}"

    return render_template(
        "note.html",
        note_id=note_id,
        content=soup.prettify(),
        title=note.title,
        date=note.created_at.strftime("%Y-%m-%d"),
        tags=note.tags,
        prev_url=prev_url,
        next_url=next_url,
    )


@app.route("/tag/<tag>")
def show_tag(tag):
    """Show notes with specific tag"""
    notes = get_all_notes()
    tagged_notes = []

    tag = tag.lower()
    for note in notes:
        if tag in [t.lower() for t in note.tags]:
            # Read the content and extract a snippet
            content = note.raw_content
            soup = BeautifulSoup(content, "html.parser")

            # Get first paragraph or similar for snippet
            snippet = soup.find(["p", "div"])
            if snippet:
                note.snippet = str(snippet)
            tagged_notes.append(note)

    return render_template("tag.html", tag=tag, notes=tagged_notes)


@app.route("/tags")
def show_all_tags():
    """Show all available tags"""
    notes = get_all_notes()
    all_tags = set()
    for note in notes:
        all_tags.update(tag.lower() for tag in note.tags)
    return render_template("tags.html", tags=sorted(all_tags))


@app.post("/share/<int:note_id>")
def share_note(note_id):
    """Generate a standalone shared version of a note"""
    note = get_note_by_id(note_id)
    if not note:
        return abort(500, "Note not found")
    # Create a temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        tufte_css = (settings.static_dir / "tufte.css").read_text()

        standalone_html = render_template(
            "shared_note.html",
            content=str(note.article_content),
            title=note.title,
            date=note.created_at.strftime("%Y-%m-%d"),
            tags=note.tags,
            tufte_css=tufte_css,
        )

        # Save HTML file
        file_hash = _get_note_hash(note.title)
        output_file = temp_path / f"{file_hash}.html"
        output_file.write_text(standalone_html)

        # SCP the file
        logging.info("Copying file to %s", settings.scp_target)
        subprocess.check_call(["scp", str(output_file), settings.scp_target])
        return jsonify(
            {
                "success": True,
                "url": f"{settings.public_share_url}/{file_hash}.html",
            }
        )


@app.route("/graph")
def render_graph():
    """Render a graphviz diagram"""
    dot_data = request.args.get("dot")
    if not dot_data:
        abort(400, "No graph data provided")

    # Decode the base64 dot data
    dot_content = base64.urlsafe_b64decode(dot_data).decode()
    dot = graphviz.Source(dot_content)

    # Render to SVG
    svg_data = dot.pipe(format="svg")

    # Parse the SVG to add styling
    svg_soup = BeautifulSoup(svg_data)

    # Find the root SVG element
    svg: Tag = svg_soup.find("svg")  # type: ignore
    if svg:
        # Add styling attributes
        svg["style"] = "background-color: transparent;"

        # Style the nodes
        for node in svg_soup.find_all("g", class_="node"):
            ellipse = node.find("ellipse") or node.find("polygon")
            if ellipse:
                ellipse["fill"] = "#f7f7f7"
                ellipse["stroke"] = "#2b2b2b"
                ellipse["stroke-width"] = "2"
            text = node.find("text")
            if text:
                text["font-family"] = "Helvetica"
                text["font-size"] = "14px"

        # Style the edges
        for edge in svg_soup.find_all("g", class_="edge"):
            path = edge.find("path")
            if path:
                path["stroke"] = "#2b2b2b"
                path["stroke-width"] = "1.5"
            arrow = edge.find("polygon")
            if arrow:
                arrow["fill"] = "#2b2b2b"
                arrow["stroke"] = "#2b2b2b"

    # Return the modified SVG
    return Response(str(svg_soup), mimetype="image/svg+xml")


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    """Handle file uploads via drag-and-drop."""
    if request.method != "POST":
        return render_template("upload.html")

    if "pdf" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"}), 400

    file = request.files["pdf"]
    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected"}), 400

    allowed_extensions = {'.pdf', '.png', '.jpg', '.jpeg', '.heic'}
    if not any(file.filename.lower().endswith(ext) for ext in allowed_extensions):
        return (
            jsonify({"success": False, "error": "Only PDF and image files (PNG, JPG, HEIC) are allowed"}),
            400,
        )

    if not current_user.is_authenticated:
        return jsonify({
            "success": False, 
            "error": "Authentication required. Please check src/noteomatic/config.py for OAuth setup."
        }), 401

    # Save the uploaded file in user's raw directory
    upload_dir: Path = current_user.raw_dir
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / file.filename
    file.save(str(file_path))

    try:
        # Process the uploaded PDF into user's notes directory
        submit_files(file_path, upload_dir, current_user.notes_dir)
        # reload the database
        _init()
        return jsonify({"success": True})
    except Exception as e:
        return (
            jsonify(
                {"success": False, "error": str(e), "traceback": traceback.format_exc()}
            ),
            500,
        )


@app.route("/sync", methods=["POST"])
@login_required
def sync():
    """Handle syncing of selected files from Google Picker."""
    data = request.json
    file_id = data.get("fileId")
    if not file_id:
        return jsonify({"error": "No file ID provided"}), 400

    # Get Google Drive service
    service = get_google_drive_service()

    # Get file metadata
    file = service.files().get(fileId=file_id, fields="name, mimeType").execute()
    file_name = file["name"]
    mime_type = file["mimeType"]

    if mime_type != "application/pdf":
        return jsonify({"error": "Only PDF files are supported"}), 400

    if not current_user.is_authenticated:
        return jsonify({"error": "Authentication required"}), 401

    # Download the file to user's raw directory
    local_path = current_user.raw_dir / file_name
    download_request = service.files().get_media(fileId=file_id)
    with open(local_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, download_request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            if status:
                print(f"Downloading {file_name}: {int(status.progress() * 100)}%")

    # Process the file in user's directories
    submit_files(local_path, current_user.raw_dir, current_user.notes_dir)
    return jsonify({"success": True, "message": f"Processed {file_name}"})


@app.route("/note/<int:note_id>/edit", methods=["GET"])
def edit_note(note_id):
    """Show edit form for a note"""
    note = get_note_by_id(note_id)
    if not note:
        abort(404, "Note not found")
    
    return render_template(
        "edit.html",
        note_id=note_id,
        content=note.raw_content,
        title=note.title
    )

@app.route("/note/<int:note_id>/save", methods=["POST"])
def save_note(note_id):
    """Save changes to a note"""
    note = get_note_by_id(note_id)
    if not note:
        abort(404, "Note not found")

    content = request.form.get("content")
    if not content:
        abort(400, "No content provided")

    # update note file on disk and then reload the database
    note_path = settings.notes_dir / note.path
    logging.info("Updating note: %s", note_path)
    with open(note_path, "w") as f:
        f.write(content)

    # reload the database
    _init()

    return redirect(url_for("show_note", note_id=note_id))

@app.route("/login")
def login():
    """Handle login with Google OAuth"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    flow = User.get_google_oauth_flow()
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='select_account'  # Force Google account selection
    )
    return redirect(authorization_url)

@app.route("/login/callback")
def oauth_callback():
    """Handle Google OAuth callback"""
    flow = User.get_google_oauth_flow()
    flow.fetch_token(authorization_response=request.url)
    
    credentials = flow.credentials
    user = User.from_google_credentials(credentials)
    if user:
        # Store user data in session
        session['user_data'] = user.to_dict()
        login_user(user)
        return redirect(url_for('index'))
    else:
        flash('Login failed')
        return redirect(url_for('login'))

@app.route("/logout")
@login_required
def logout():
    """Handle logout"""
    # Clear Flask-Login session
    logout_user()
    # Clear Flask session
    session.clear()
    # Redirect to login page with cache-control headers
    response = redirect(url_for('login'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

if __name__ == "__main__":
    app.run(debug=settings.debug)
