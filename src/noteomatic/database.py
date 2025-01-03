import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, List, Optional

from bs4 import BeautifulSoup, Tag
from sqlalchemy import (
    JSON,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    event,
    select,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from noteomatic import config


class SqliteConnection:
    def __init__(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=True)
        self.engine = create_engine(url=f"sqlite:///{self.tmp.name}")

        if config.settings.db.sqlite_wal:
            # Enable WAL mode
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                if isinstance(dbapi_connection, sqlite3.Connection):
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA busy_timeout=10000")  # 10s timeout
                    cursor.close()


connection = SqliteConnection()
SessionLocal = sessionmaker(bind=connection.engine)

class Base(DeclarativeBase):
    """Base class for SQLAlchemy models"""
    pass


def parse_html_content(content: str):
    """Parse HTML content and return article content."""
    soup = BeautifulSoup(content, "html.parser")
    return soup.find("article") or soup.find("body") or soup


class NoteModel(Base):
    """Database model for notes"""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    @property
    def raw_content(self) -> str:
        return self.content

    @property
    def article_content(self):
        return parse_html_content(self.content)

    @classmethod
    def from_file(cls, file_path: Path, notes_dir: Path, user_id: str) -> tuple[str, "NoteModel"]:
        """Create a note instance from a file"""
        content = file_path.read_text()
        soup = BeautifulSoup(content, "html.parser")

        # Parse metadata and look for title and tags.
        title_meta = soup.find("meta", {"name": "title"})
        title = title_meta["content"] if title_meta else ""

        # if no meta title, look for h1
        if not title:
            title = soup.find("h1").text if soup.find("h1") else ""
        if not title:
            title = soup.find("h2").text if soup.find("h2") else ""
        if not title:
            title = soup.find("h3").text if soup.find("h3") else ""

        if not title:
            title = file_path.stem

        # Parse date for created_at
        date_meta = soup.find("meta", {"name": "date"})
        created_at = None
        if date_meta and date_meta["content"]:
            for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                try:
                    created_at = datetime.strptime(date_meta["content"], fmt)
                    break
                except ValueError:
                    continue

        if not created_at:
            created_at = datetime.fromtimestamp(file_path.stat().st_ctime)

        tags_meta = soup.find("meta", {"name": "tags"})
        tags = []
        if tags_meta and tags_meta["content"]:
            tags = [tag.strip().lower() for tag in tags_meta["content"].split(",")]

        # Create note instance
        note = cls(
            user_id=user_id,  # Ensure user_id is passed through
            path=str(file_path.relative_to(notes_dir)),
            title=title,
            content=content,
            created_at=created_at,
            tags=tags,
        )
        
        # Double check user_id is set
        if not note.user_id:
            raise ValueError(f"User ID not set for note {title}")

        return content, note


class NoteRepository:
    """Repository for database operations on notes"""

    def __init__(self, session: Session, user_id: Optional[str] = None):
        self.session = session
        self.user_id = user_id

    def get_by_id(self, note_id: int) -> Optional[NoteModel]:
        """Get a note by its ID"""
        return self.session.get(NoteModel, note_id)

    def get_all(self) -> List[NoteModel]:
        """Get all notes ordered by creation date"""
        stmt = select(NoteModel)
        if self.user_id:
            stmt = stmt.where(NoteModel.user_id == self.user_id)
        stmt = stmt.order_by(NoteModel.created_at.desc(), NoteModel.title.desc())
        return list(self.session.execute(stmt).scalars().all())

    def count(self) -> int:
        """Count total number of notes"""
        query = self.session.query(NoteModel)
        if self.user_id:
            query = query.filter(NoteModel.user_id == self.user_id)
        return query.count()

    def create(
        self,
        title: str,
        path: str,
        content: str,
        tags: List[str],
        created_at: Optional[datetime] = None,
        user_id: Optional[str] = None,
    ) -> NoteModel:
        """Create a new note or update existing one with same title"""
        existing_note = self.get_by_title(title)

        if existing_note:
            # Update existing note
            existing_note.path = path
            existing_note.content = content
            existing_note.tags = tags
            # Don't update created_at for existing notes
            note = existing_note
        else:
            # Create new note
            note = NoteModel(
                title=title,
                path=path,
                content=content,
                tags=tags,
                created_at=created_at,
                user_id=user_id or self.user_id,  # Use provided user_id or fall back to repo's user_id
            )
            self.session.add(note)
        self.session.commit()
        self.session.refresh(note)
        return note

    def search(self, query: str) -> List[NoteModel]:
        """Search notes using full-text search"""
        fts_query = text("SELECT rowid FROM notes_fts WHERE notes_fts MATCH :query")
        matching_ids = self.session.execute(fts_query, {"query": query}).scalars()
        stmt = select(NoteModel).where(NoteModel.id.in_(matching_ids))
        return list(self.session.execute(stmt).scalars().all())

    def get_by_tag(self, tag: str) -> List[NoteModel]:
        """Get all notes with a specific tag"""
        stmt = select(NoteModel).where(NoteModel.tags.contains([tag]))
        return list(self.session.execute(stmt).scalars().all())

    def get_all_tags(self) -> List[str]:
        """Get all unique tags"""
        notes = self.get_all()
        tags = set()
        for note in notes:
            tags.update(note.tags)
        return sorted(tags)

    def get_by_title(self, title: str) -> Optional[NoteModel]:
        """Get a note by its title"""
        stmt = select(NoteModel).where(NoteModel.title == title)
        return self.session.execute(stmt).scalar_one_or_none()

    def reset(self):
        """Reset the database"""
        Base.metadata.drop_all(self.session.get_bind())
        Base.metadata.create_all(self.session.get_bind())
        
        # Create FTS virtual table
        self.session.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts 
            USING fts5(title, content, tags, content='notes', content_rowid='id')
        """))
        
        # Create triggers to keep FTS table in sync
        self.session.execute(text("""
            CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid, title, content, tags) 
                VALUES (new.id, new.title, new.content, new.tags);
            END
        """))
        
        self.session.execute(text("""
            CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, title, content, tags) 
                VALUES('delete', old.id, old.title, old.content, old.tags);
            END
        """))
        
        self.session.execute(text("""
            CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, title, content, tags) 
                VALUES('delete', old.id, old.title, old.content, old.tags);
                INSERT INTO notes_fts(rowid, title, content, tags) 
                VALUES (new.id, new.title, new.content, new.tags);
            END
        """))
        
        self.session.commit()


db = SessionLocal()

@contextmanager
def get_repo(user_id: Optional[str] = None) -> Generator[NoteRepository, None, None]:
    """Get repository instance with context management"""
    try:
        yield NoteRepository(db, user_id)
    finally:
        db.close()
