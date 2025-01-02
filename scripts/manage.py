import logging
from pathlib import Path

import typer
from sqlalchemy import create_engine, text
from sqlalchemy_utils import create_database, database_exists

from noteomatic.config import settings
from noteomatic.database import Base
from noteomatic.lib import submit_files, sync_from_drive

app = typer.Typer()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)


@app.command("list-schema")
def list_schema():
    """List the database schema"""
    engine = create_engine(settings.db.get_url())
    with engine.connect() as connection:
        sql = text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        result = connection.execute(sql)
        tables = result.fetchall()

    typer.echo("Tables:")
    for table in tables:
        typer.echo(f"- {table[0]}")


@app.command("reset-db")
def reset_db(force: bool = typer.Option(False, "--force", "-f", help="Force reset without confirmation")):
    """Reset database tables - WARNING: This will delete all data!"""
    if not force:
        typer.confirm("⚠️  This will delete all data. Are you sure?", abort=True)

    engine = create_engine(settings.db.get_url())
    # create the DB using sqlalchemy-util and the engine url
    if not database_exists(engine.url):
        create_database(engine.url)

    # Drop all tables
    Base.metadata.drop_all(engine)
    typer.echo("Dropped all tables")

    # Recreate tables
    Base.metadata.create_all(engine)
    typer.echo("Created new tables")

    typer.echo("✅ Database reset complete")


@app.command()
def sync(
    drive_folder: str = typer.Option("Notes", help="Google Drive folder to sync from"),
    raw_dir: Path = typer.Option("raw", help="Directory for storing raw files"),
    build_dir: Path = typer.Option("build", help="Directory for build artifacts"),
):
    """Sync PDFs from Google Drive and process them."""
    new_files = sync_from_drive(drive_folder, raw_dir, build_dir)
    if new_files:
        typer.echo(f"Processed {len(new_files)} new files")
    else:
        typer.echo("No new files to process")


@app.command()
def submit(
    source: Path = typer.Option(..., help="PDF file or directory to process"),
    raw_dir: Path = typer.Option("raw", help="Directory for storing raw files"),
    build_dir: Path = typer.Option("build", help="Directory for build artifacts"),
):
    """Submit a new PDF or directory of PDFs for processing."""
    processed_files = submit_files(source, raw_dir, build_dir)
    typer.echo(f"Processed {len(processed_files)} files")


if __name__ == "__main__":
    app()
