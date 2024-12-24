import glob
import logging
import pickle
import shutil
from pathlib import Path
from typing import List

import typer
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from noteomatic.llm import process_images_with_llm
from noteomatic.notes import save_notes, split_notes
from noteomatic.pdf import extract_images_from_pdf

app = typer.Typer()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)


def process_pdf_files(sources: List[Path], raw_dir: Path, build_dir: Path):
    """Process a list of PDF files and generate notes."""
    for pdf_file in sources:
        source_name = pdf_file.stem
        image_dir = build_dir / "images" / source_name
        notes_dir = build_dir / "notes" / source_name

        image_dir.mkdir(parents=True, exist_ok=True)
        notes_dir.mkdir(parents=True, exist_ok=True)

        # Extract images from PDF
        images = extract_images_from_pdf(pdf_file)
        typer.echo(f"Extracted {len(images)} images from {pdf_file}")

        # Process with LLM
        results = process_images_with_llm(images)

        # Save notes
        notes = split_notes(results)
        save_notes(notes, notes_dir)

        typer.echo(f"Processed {pdf_file} -> {len(notes)} notes")

def get_google_drive_service():
    """Get authenticated Google Drive service."""
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
    creds = None
    token_path = Path('credentials/token.pickle')
    credentials_path = Path('credentials/client_secret.json')

    if token_path.exists():
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)

    return build('drive', 'v3', credentials=creds)

@app.command()
def sync(
    drive_folder: str = typer.Option("Notes", help="Google Drive folder to sync from"),
    raw_dir: Path = typer.Option("raw", help="Directory for storing raw files"),
    build_dir: Path = typer.Option("build", help="Directory for build artifacts"),
):
    """Sync PDFs from Google Drive and process them."""
    raw_dir.mkdir(exist_ok=True)
    build_dir.mkdir(exist_ok=True)

    # Get Google Drive service
    service = get_google_drive_service()

    # Find the Notes folder
    folder_results = service.files().list(
        q=f"name='{drive_folder}' and mimeType='application/vnd.google-apps.folder'",
        spaces='drive',
        fields='files(id, name)'
    ).execute()

    if not folder_results['files']:
        typer.echo(f"Folder '{drive_folder}' not found in Google Drive")
        return

    folder_id = folder_results['files'][0]['id']

    # List PDF files in the folder
    results = service.files().list(
        q=f"'{folder_id}' in parents and mimeType='application/pdf'",
        spaces='drive',
        fields='files(id, name)'
    ).execute()

    new_files = []
    for file in results.get('files', []):
        local_path = raw_dir / file['name']
        
        # Skip if file already exists
        if local_path.exists():
            continue

        # Download the file
        request = service.files().get_media(fileId=file['id'])
        with open(local_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
                if status:
                    typer.echo(f"Downloading {file['name']}: {int(status.progress() * 100)}%")
        
        new_files.append(local_path)

    if new_files:
        typer.echo(f"Processing {len(new_files)} new files...")
        process_pdf_files(new_files, raw_dir, build_dir)
    else:
        typer.echo("No new files to process")

@app.command()
def submit(
    source: Path = typer.Option(..., help="PDF file or directory to process"),
    raw_dir: Path = typer.Option("raw", help="Directory for storing raw files"),
    build_dir: Path = typer.Option("build", help="Directory for build artifacts"),
):
    """Submit a new PDF or directory of PDFs for processing."""
    raw_dir.mkdir(exist_ok=True)
    build_dir.mkdir(exist_ok=True)

    source = source.expanduser()

    # Copy source to raw directory
    sources = []
    if source.is_file():
        shutil.copy2(source, raw_dir / source.name)
        sources.append(raw_dir / source.name)
    else:
        for pdf in glob.glob(str(source.resolve())):
            shutil.copy2(pdf, raw_dir / Path(pdf).name)
            sources.append(raw_dir / Path(pdf).name)

    process_pdf_files(sources, raw_dir, build_dir)


if __name__ == "__main__":
    app()
