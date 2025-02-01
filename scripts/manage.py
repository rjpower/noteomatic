import logging
from pathlib import Path

import typer

from noteomatic.lib import extract_from_files

app = typer.Typer()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)


@app.command()
def extract(
    source: Path = typer.Option(..., help="PDF file or directory to process"),
    raw_dir: Path = typer.Option("raw", help="Directory for storing raw files"),
    build_dir: Path = typer.Option("build", help="Directory for build artifacts"),
):
    """Submit a new PDF or directory of PDFs for processing."""
    processed_files = extract_from_files(source, raw_dir, build_dir)
    typer.echo(f"Processed {len(processed_files)} files")


if __name__ == "__main__":
    app()
