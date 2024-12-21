import base64
import os
from dataclasses import dataclass
from datetime import datetime
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple

import graphviz
from bs4 import BeautifulSoup
from flask import Flask, Response, abort, render_template, request, send_from_directory

ROOT_DIR = Path(__file__).parent.parent.parent
NOTES_DIR = ROOT_DIR / "build" / "notes"
app = Flask(
    __name__,
    static_url_path="/static",
    static_folder=ROOT_DIR / "static",
    template_folder=Path(__file__).parent / "templates",
)

# Cache for database connection and notes
_db_connection = None


@dataclass
class NoteMetadata:
    path: str
    title: str
    date: Optional[str]
    datetime: Optional[datetime]
    tags: List[str]
    snippet: Optional[str] = None


def parse_note_metadata(file_path: Path, content: str) -> NoteMetadata:
    soup = BeautifulSoup(content, "html.parser")

    title = soup.find("meta", {"name": "title"})
    title = title["content"] if title else file_path.stem

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
    tags = tags_meta["content"].split(",") if tags_meta else []
    tags = [tag.strip() for tag in tags]

    return NoteMetadata(
        path=str(file_path.relative_to(NOTES_DIR)),
        title=title,
        date=date,
        datetime=parsed_datetime,
        tags=tags
    )

@app.route("/search")
def search():
    """Search notes using FTS"""
    query = request.args.get("q")
    if not query:
        return render_template("search.html", error="No query provided")

    conn = get_db_connection()
    cursor = conn.execute(
        """
        SELECT *
        FROM notes_fts
        WHERE notes_fts MATCH ?
        ORDER BY bm25(notes_fts), datetime DESC, title DESC
        """,
        (query,),
    )
    search_results = [
        NoteMetadata(
            path=row["path"],
            title=row["title"],
            date=row["date"],
            datetime=datetime.fromisoformat(row["datetime"]) if row["datetime"] else None,
            tags=row["tags"].split(","),
        )
        for row in cursor
    ]

    # Extract snippets
    for note in search_results:
        note_path = NOTES_DIR / note.path
        content = note_path.read_text()
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


def get_db_connection():
    """Get a connection to the database, using cache if available"""
    global _db_connection
    if _db_connection is None:
        _db_connection = sqlite3.connect(":memory:")
        _db_connection.row_factory = sqlite3.Row
        _db_connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(title, content, tags, path, date, datetime, tokenize='porter')")
        _load_all_notes()
    return _db_connection

def _load_all_notes() -> None:
    """Load all notes into memory and populate the FTS table"""
    conn = get_db_connection()
    conn.execute("DELETE FROM notes_fts")  # Clear existing data

    for root, _, files in os.walk(NOTES_DIR):
        for file in files:
            if file.endswith(".html"):
                file_path = Path(root) / file
                content = file_path.read_text()
                metadata = parse_note_metadata(file_path, content)

                # Insert into FTS table
                conn.execute(
                    "INSERT INTO notes_fts (title, content, tags, path, date, datetime) VALUES (?, ?, ?, ?, ?, ?)",
                    (metadata.title, content, ",".join(metadata.tags), metadata.path, metadata.date, metadata.datetime),
                )
    conn.commit()


def get_all_notes() -> List[NoteMetadata]:
    """Get all notes from the database"""
    conn = get_db_connection()
    cursor = conn.execute("SELECT * FROM notes_fts ORDER BY datetime DESC, title DESC")
    notes = [
        NoteMetadata(
            path=row["path"],
            title=row["title"],
            date=row["date"],
            datetime=datetime.fromisoformat(row["datetime"]) if row["datetime"] else None,
            tags=row["tags"].split(","),
        )
        for row in cursor
    ]
    return notes


@app.route("/")
def index():
    """List all available notes"""
    notes = get_all_notes()
    return render_template("index.html", notes=notes, show_search=True)


@app.route("/notes/<path:note_path>")
def show_note(note_path):
    """Display a specific note"""
    note_file = NOTES_DIR / note_path

    if not note_file.exists():
        abort(404, "Note not found")

    content = note_file.read_text()
    soup = BeautifulSoup(content, "html.parser")

    # Extract just the body content, or article if we find one.
    body_content = soup.find("article")

    if not body_content:
        body_content = soup.find("body")

    if not body_content:
        abort(500, "Invalid note format")

    # Process any graph tags
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

    metadata = parse_note_metadata(note_file, content)

    # compute prev_url and next_url, based on this path in the sorted list
    notes = get_all_notes()
    note_index = None
    for i, note in enumerate(notes):
        if note.path == metadata.path:
            note_index = i
            break

    prev_url = None
    next_url = None

    if note_index is not None:
        if note_index > 0:
            prev_url = "/notes/" + notes[note_index - 1].path
        if note_index < len(notes) - 1:
            next_url = "/notes/" + notes[note_index + 1].path

    return render_template(
        "note.html",
        content=str(body_content),
        title=metadata.title,
        date=metadata.date,
        tags=metadata.tags,
        prev_url=prev_url,
        next_url=next_url,
    )


@app.route("/tag/<tag>")
def show_tag(tag):
    """Show notes with specific tag"""
    notes = get_all_notes()
    tagged_notes = []

    for note in notes:
        if tag in note.tags:
            # Read the content and extract a snippet
            note_path = NOTES_DIR / note.path
            content = note_path.read_text()
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
        all_tags.update(note.tags)
    return render_template("tags.html", tags=sorted(all_tags))


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
    svg = svg_soup.find("svg")
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


if __name__ == "__main__":
    # Invalidate cache on startup
    get_db_connection()

    app.run(debug=True)
