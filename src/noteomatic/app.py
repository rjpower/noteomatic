import base64
import hashlib
import logging
import os
import sqlite3
import subprocess
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import bs4
import graphviz
from bs4 import BeautifulSoup, Tag
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
)
from googleapiclient.http import MediaIoBaseDownload
from pydantic import BaseModel, ConfigDict, Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

from noteomatic.lib import get_google_drive_service, process_pdf_files


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NOTEOMATIC_", env_file=".env", env_file_encoding="utf-8"
    )

    root_dir: Path = Path(__file__).parent.parent.parent
    scp_target: str = Field(
        default="user@example.com:/var/www/html/shared",
        description="SCP target for sharing notes",
    )
    public_share_url: str = ""
    build_dir: Path = root_dir / "build"
    raw_dir: Path = root_dir / "raw"
    notes_dir: Path = build_dir / "notes"
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: str = Field(default="INFO", description="Logging level")
    database_url: Optional[PostgresDsn] = Field(
        default=None, description="Database connection URL"
    )

    @property
    def static_dir(self) -> Path:
        return self.root_dir / "static"

    @property
    def template_dir(self) -> Path:
        return Path(__file__).parent / "templates"


settings = AppSettings()
NOTES_DIR = settings.notes_dir

app = Flask(
    __name__,
    static_url_path="/static",
    static_folder=str(settings.static_dir),
    template_folder=str(settings.template_dir),
)

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

# Cache for database connection
_db_connection = None

class NoteMetadata(BaseModel):
    path: str
    title: str
    date: Optional[str]
    datetime: Optional[datetime]
    tags: List[str]
    snippet: Optional[str] = None


class Note(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = None
    metadata: NoteMetadata
    raw_content: str
    article_content: Tag
    graphs: List[Tag]

    snippet: str = ""

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "Note":
        """Create a Note from a database row"""
        payload = row["payload"]
        metadata = NoteMetadata.model_validate_json(row["metadata"])
        return cls.parse(payload, metadata.path).model_copy(update={"id": row["id"]})

    @classmethod
    def from_file(cls, file_path: Path) -> "Note":
        """Create a Note by parsing a file"""
        content = file_path.read_text()
        return cls.parse(content, path=str(file_path.relative_to(NOTES_DIR)))

    @classmethod
    def parse(cls, content: str, path: str) -> "Note":
        """Parse note content into a Note instance"""
        soup = BeautifulSoup(content, "html.parser")

        # Parse metadata
        title = soup.find("meta", {"name": "title"})
        title = title["content"] if title else Path(path).stem

        date_meta = soup.find("meta", {"name": "date"})
        date = date_meta["content"] if date_meta else None

        # Try to parse the date into a datetime object
        parsed_datetime = None
        if date:
            try:
                # Try common formats
                for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                    try:
                        parsed_datetime = datetime.strptime(date, fmt)
                        break
                    except ValueError:
                        continue
            except Exception:
                parsed_datetime = None

        tags_meta = soup.find("meta", {"name": "tags"})
        tags = []
        if tags_meta and tags_meta["content"]:
            tags = tags_meta["content"].split(",")
            tags = [tag.strip().lower() for tag in tags]

        metadata = NoteMetadata(
            path=path,
            title=title,
            date=date,
            datetime=parsed_datetime,
            tags=tags,
        )

        # Extract body content
        article_content = soup.find("article") or soup.find("body") or soup

        # Find all graph tags
        graphs = soup.find_all("graph")

        return cls(
            metadata=metadata,
            raw_content=content,
            article_content=article_content,
            graphs=graphs,
        )


def _create_tables(conn):
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
      CREATE TABLE IF NOT EXISTS notes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          metadata TEXT NOT NULL,
          payload TEXT NOT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
  """
    )

    conn.execute(
        """
      CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts 
      USING fts5(note_id, title, path, content, tags, date, datetime, tokenize='porter')
  """
    )


def get_db_connection():
    """Get a connection to the database, using cache if available"""
    global _db_connection
    if _db_connection is None:
        _db_connection = sqlite3.connect(":memory:")
        _load_all_notes(_db_connection)

    return _db_connection


def _get_note_hash(title: str) -> str:
    """Generate a consistent hash for note sharing"""
    return hashlib.md5(title.encode()).hexdigest()[:8]


def _load_all_notes(conn) -> None:
    """Load all notes into database"""
    conn.execute("DROP TABLE IF EXISTS notes")
    conn.execute("DROP TABLE IF EXISTS notes_fts")
    _create_tables(conn)

    for root, _, files in os.walk(settings.notes_dir):
        for file in files:
            if file.endswith(".html"):
                file_path = Path(root) / file
                parsed_note = Note.from_file(file_path)

                # Insert into main notes table
                cursor = conn.execute(
                    "INSERT INTO notes (title, metadata, payload, created_at) VALUES (?, ?, ?, ?)",
                    (
                        parsed_note.metadata.title,
                        parsed_note.metadata.model_dump_json(),
                        file_path.read_text(),
                        parsed_note.metadata.datetime.isoformat(),
                    ),
                )
                note_id = cursor.lastrowid

                # Insert into FTS table
                conn.execute(
                    "INSERT INTO notes_fts (note_id, title, path, content, tags, date, datetime) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        note_id,
                        parsed_note.metadata.title,
                        parsed_note.metadata.path,
                        parsed_note.raw_content,
                        ",".join(parsed_note.metadata.tags),
                        parsed_note.metadata.date,
                        parsed_note.metadata.datetime,
                    ),
                )
    conn.commit()


def get_note_by_id(note_id: int) -> Note:
    """Get a note by its ID"""
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        raise KeyError(f"Note with ID {note_id} not found")

    return Note.from_db_row(row)


def get_all_notes() -> List[Note]:
    """Get all notes from the database"""
    conn = get_db_connection()
    cursor = conn.execute(
        """
        SELECT n.id, n.title, n.metadata, n.payload 
        FROM notes n
        ORDER BY n.created_at DESC, n.title DESC
    """
    )
    return [
        Note.from_db_row(row)
        for row in cursor
    ]


def count_notes() -> int:
    """Count the number of notes in the database"""
    conn = get_db_connection()
    cursor = conn.execute("SELECT COUNT(*) FROM notes")
    return cursor.fetchone()[0]


@app.route("/search")
def search():
    """Search notes using FTS"""
    query = request.args.get("q")
    if not query:
        return render_template("search.html", error="No query provided")

    conn = get_db_connection()
    cursor = conn.execute(
        """
        SELECT notes.*
        FROM notes_fts
        JOIN notes ON notes.id = notes_fts.note_id
        WHERE notes_fts MATCH ?
        ORDER BY bm25(notes_fts), datetime DESC, title DESC
        """,
        (query,),
    )
    search_results = [Note.from_db_row(row) for row in cursor]

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


@app.route("/note/<int:note_id>")
def show_note(note_id):
    """Display a specific note"""
    note = get_note_by_id(note_id)
    if not note:
        abort(404, "Note not found")

    # Process any graph tags
    soup = bs4.BeautifulSoup(note.raw_content, "html.parser")
    for graph_tag in note.graphs:
        # Create an img tag to replace the graph
        img = soup.new_tag("img")
        graph_content = graph_tag.string or ""
        img["src"] = (
            f"/graph?dot={base64.urlsafe_b64encode(graph_content.encode()).decode()}"
        )
        img["class"] = "graph"
        img["style"] = "max-width: 100%; height: auto;"
        graph_tag.replace_with(img)

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
        content=str(note.article_content),
        title=note.metadata.title,
        date=note.metadata.date,
        tags=note.metadata.tags,
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
        if tag in [t.lower() for t in note.metadata.tags]:
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
        all_tags.update(tag.lower() for tag in note.metadata.tags)
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
            title=note.metadata.title,
            date=note.metadata.date,
            tags=note.metadata.tags,
            tufte_css=tufte_css,
        )

        # Save HTML file
        file_hash = _get_note_hash(note.metadata.title)
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
        process_pdf_files([file_path], upload_dir, Path(settings.build_dir))
        _load_all_notes(_db_connection)
        return jsonify({"success": True})
    except Exception as e:
        return (
            jsonify(
                {"success": False, "error": str(e), "traceback": traceback.format_exc()}
            ),
            500,
        )


@app.route("/sync", methods=["POST"])
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

    # Download the file
    local_path = Path(app.config["RAW_DIR"]) / file_name
    download_request = service.files().get_media(fileId=file_id)
    with open(local_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, download_request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            if status:
                print(f"Downloading {file_name}: {int(status.progress() * 100)}%")

    # Process the file
    process_pdf_files(
        [local_path], Path(app.config["RAW_DIR"]), Path(app.config["BUILD_DIR"])
    )
    _load_all_notes(_db_connection)

    return jsonify({"success": True, "message": f"Processed {file_name}"})


if __name__ == "__main__":
    app.run(debug=settings.debug)
