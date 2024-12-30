from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, List, Optional

from bs4 import BeautifulSoup, Tag
from sqlalchemy import JSON, DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from noteomatic import config

engine = create_engine(config.settings.db.get_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

class Base(DeclarativeBase):
    """Base class for SQLAlchemy models"""
    pass


def parse_html_content(content: str) -> Tag:
    """Parse HTML content and return article content."""
    soup = BeautifulSoup(content, "html.parser")
    article_content = soup.find("article") or soup.find("body") or soup
    return article_content


class NoteModel(Base):
    """Database model for notes"""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
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
    def article_content(self) -> Tag:
        return parse_html_content(self.content)

    @classmethod
    def from_file(cls, file_path: Path, notes_dir: Path) -> tuple[str, "NoteModel"]:
        """Create a note instance from a file"""
        content = file_path.read_text()
        soup = BeautifulSoup(content, "html.parser")

        # Parse metadata
        title_meta = soup.find("meta", {"name": "title"})
        title = title_meta["content"] if title_meta else file_path.stem

        # Parse date for created_at
        date_meta = soup.find("meta", {"name": "date"})
        created_at = datetime.utcnow()
        if date_meta and date_meta["content"]:
            for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                try:
                    created_at = datetime.strptime(date_meta["content"], fmt)
                    break
                except ValueError:
                    continue

        tags_meta = soup.find("meta", {"name": "tags"})
        tags = []
        if tags_meta and tags_meta["content"]:
            tags = [tag.strip().lower() for tag in tags_meta["content"].split(",")]

        # Create note instance
        note = cls(
            path=str(file_path.relative_to(notes_dir)),
            title=title,
            content=content,
            created_at=created_at,
            tags=tags,
        )

        return content, note


class NoteRepository:
    """Repository for database operations on notes"""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, note_id: int) -> Optional[NoteModel]:
        """Get a note by its ID"""
        return self.db.get(NoteModel, note_id)

    def get_all(self) -> List[NoteModel]:
        """Get all notes ordered by creation date"""
        stmt = select(NoteModel).order_by(
            NoteModel.created_at.desc(), NoteModel.title.desc()
        )
        return list(self.db.execute(stmt).scalars().all())

    def count(self) -> int:
        """Count total number of notes"""
        return self.db.query(NoteModel).count()

    def create(
        self,
        title: str,
        path: str,
        content: str,
        tags: List[str],
        created_at: Optional[datetime] = None,
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
            )
            self.db.add(note)
        self.db.commit()
        self.db.refresh(note)
        return note

    def search(self, query: str) -> List[NoteModel]:
        """Search notes using full-text search"""
        # This is a basic implementation - you might want to use PostgreSQL's
        # full-text search capabilities for better results
        stmt = select(NoteModel).where(
            NoteModel.content.ilike(f"%{query}%") | NoteModel.title.ilike(f"%{query}%")
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_by_tag(self, tag: str) -> List[NoteModel]:
        """Get all notes with a specific tag"""
        stmt = select(NoteModel).where(NoteModel.tags.contains([tag]))
        return list(self.db.execute(stmt).scalars().all())

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
        return self.db.execute(stmt).scalar_one_or_none()


@contextmanager
def get_repo() -> Generator[NoteRepository, None, None]:
    """Get repository instance with context management"""
    db = SessionLocal()
    # create all tables for convenience with SQlite/in-memory
    Base.metadata.create_all(engine)
    try:
        yield NoteRepository(db)
    finally:
        db.close()
