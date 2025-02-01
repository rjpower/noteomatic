import base64
import logging
import os
import re
import subprocess
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import List

import bs4
import graphviz
from bs4 import BeautifulSoup, Tag
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from markdown_it import MarkdownIt
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

from noteomatic.config import settings
from noteomatic.demo.database import NoteModel, get_repo
from noteomatic.lib import extract_from_files
from noteomatic.notes import note_hash

# Cache for database connection
_db_connection = None


# Initialize markdown parser
md = (
    MarkdownIt("commonmark", {"breaks": True, "html": True})
    .use(front_matter_plugin)
    .use(footnote_plugin)
    .use(tasklists_plugin)
    .enable("table")
)

def get_note_by_id(note_id: int) -> NoteModel:
    """Get a note by its ID"""
    with get_repo() as repo:
        note = repo.get_by_id(note_id)
        if not note:
            raise KeyError(f"Note with ID {note_id} not found")
        return note


def get_all_notes() -> List[NoteModel]:
    """Get all notes from the database"""
    with get_repo() as repo:
        notes = repo.get_all()
        for note in notes:
            # Parse content and get first two paragraphs
            soup = BeautifulSoup(note.raw_content, "html.parser")
            preview_paras = []
            for p in soup.find_all(["p", "div"]):
                if p.get_text().strip():  # Only include non-empty paragraphs
                    preview_paras.append(p.get_text().strip())
                    if len(preview_paras) == 2:
                        break
            note.preview_text = "\n".join(preview_paras) if preview_paras else ""
        return notes


def count_notes() -> int:
    """Count the number of notes in the database"""
    with get_repo() as repo:
        return repo.count()


def load_notes_from_dir(dir: Path) -> List[NoteModel]:
    """Load all notes from a directory into the database"""
    notes = []
    with get_repo() as repo:
        repo.reset()
        for dirpath, dirnames, filenames in os.walk(dir):
            for filename in filenames:
                file = Path(dirpath) / filename
                if file.is_dir() or file.suffix != ".md":
                    continue

                content, note = NoteModel.from_file(file, NOTES_DIR)

                note = repo.create(
                    title=note.title,
                    path=note.path,
                    content=content,
                    tags=note.tags,
                    created_at=note.created_at or datetime.now(),
                )
                notes.append(note)
    return notes


NOTES_DIR = settings.notes_dir
DEMO_DIR = Path(__file__).parent

app = Flask(
    __name__,
    static_url_path="/static",
    static_folder=str(DEMO_DIR / "static"),
    template_folder=str(DEMO_DIR / "templates"),
)

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


def _init():
    logging.info(f"Initializing database from {NOTES_DIR}")
    load_notes_from_dir(NOTES_DIR)


_init()


@app.route("/search")
def search():
    """Search notes using FTS"""
    query = request.args.get("q")
    if not query:
        return render_template("search.html", error="No query provided")

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

    return render_template("search.html", query=query, results=search_results)


@app.route("/")
def index():
    """List all available notes"""
    notes = get_all_notes()
    return render_template("index.html", notes=notes, show_search=True)


def process_wikilinks(content: str) -> str:
    """Convert [[tag]] syntax to links"""
    def replace_link(match):
        tag = match.group(1)
        return f'<a href="/tag/{tag}">{tag}</a>'
    
    return re.sub(r'\[\[([^\]]+)\]\]', replace_link, content)

@app.route("/note/<int:note_id>", methods=["GET"])
def show_note(note_id):
    """Display a specific note"""
    note = get_note_by_id(note_id)
    if not note:
        abort(404, "Note not found")

    # First render markdown to HTML
    html_content = md.render(note.raw_content)
    
    # Process any [[tag]] links
    html_content = process_wikilinks(html_content)

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
        content=html_content,
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
        file_hash = note_hash(note.title)
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
def upload():
    """Handle file uploads via drag-and-drop."""
    if request.method != "POST":
        return render_template("upload.html")

    if "pdf" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"}), 400

    file = request.files["pdf"]
    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected"}), 400

    if not file.filename.lower().endswith(".pdf"):
        return (
            jsonify({"success": False, "error": "Only PDF files are allowed"}),
            400,
        )

    # Save the uploaded file
    upload_dir: Path = settings.raw_dir
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / file.filename
    file.save(str(file_path))

    try:
        # Process the uploaded PDF
        extract_from_files(file_path, upload_dir, Path(settings.build_dir))
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


@app.route("/note/<int:note_id>/edit", methods=["GET"])
def edit_note(note_id):
    """Show edit form for a note"""
    note = get_note_by_id(note_id)
    if not note:
        abort(404, "Note not found")

    return render_template(
        "edit.html", note_id=note_id, content=note.raw_content, title=note.title
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


if __name__ == "__main__":
    app.run(debug=settings.debug)
