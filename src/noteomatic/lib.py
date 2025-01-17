import glob
import logging
import multiprocessing.dummy
import pickle
import shutil
from pathlib import Path
from typing import Any, List, Optional

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from noteomatic.llm import extract_notes, process_article_tags
from noteomatic.notes import save_notes, split_notes
from noteomatic.pdf import PdfOptions, extract_images_from_pdf

logger = logging.getLogger(__name__)

def get_google_drive_service(
    token_path: Path = Path('credentials/token.pickle'),
    credentials_path: Path = Path('credentials/client_secret.json')
) -> any:
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

def process_pdf_files(
    sources: List[Path], 
    raw_dir: Path, 
    build_dir: Path,
    cache_dir: Optional[Path] = None
):
    """Process a list of PDF files and generate notes."""
    # Extract all images first
    all_images = []
    for pdf_file in sources:
        logger.info(f"Extracting images from {pdf_file}")
        images = extract_images_from_pdf(pdf_file, PdfOptions())
        all_images.extend(images)

    # Process all images in one batch
    cache_dir = build_dir / "cache" if cache_dir is None else cache_dir
    note_dir = build_dir / "notes"
    cache_dir.mkdir(parents=True, exist_ok=True)
    note_dir.mkdir(parents=True, exist_ok=True)

    results = extract_notes(all_images, cache_dir=cache_dir)

    # Split and save notes
    all_notes = []
    for result in results:
        logger.info("Processing result of length %d", len(result))
        all_notes.extend(split_notes(result))

    # process tags and wiki links
    with multiprocessing.dummy.Pool(1) as pool:
        tagged_notes = pool.map(
            lambda note: process_article_tags(note, cache_dir=cache_dir), all_notes
        )

    # extract article again, since tags may have been added
    for i, note in enumerate(tagged_notes):
        if "<article>" in note and "</article>" in note:
            note = note.split("<article>")[1].split("</article>")[0]
            tagged_notes[i] = f"<article>{note}</article>"

    logger.info("Saving %d notes", len(tagged_notes))
    save_notes(tagged_notes, note_dir)


def sync_from_drive(
    drive_folder: str, raw_dir: Path, build_dir: Path, service: Optional[Any] = None
) -> List[Path]:
    """Sync PDFs from Google Drive and process them."""
    raw_dir.mkdir(exist_ok=True)
    build_dir.mkdir(exist_ok=True)

    # Get Google Drive service if not provided
    if service is None:
        service = get_google_drive_service()

    # Find the Notes folder
    folder_results = service.files().list(
        q=f"name='{drive_folder}' and mimeType='application/vnd.google-apps.folder'",
        spaces='drive',
        fields='files(id, name)'
    ).execute()

    if not folder_results['files']:
        raise ValueError(f"Folder '{drive_folder}' not found in Google Drive")

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
                    logger.info(f"Downloading {file['name']}: {int(status.progress() * 100)}%")

        new_files.append(local_path)

    if new_files:
        logger.info(f"Processing {len(new_files)} new files...")
        process_pdf_files(new_files, raw_dir, build_dir)

    return new_files


def submit_files(
    source: Path,
    raw_dir: Path,
    build_dir: Path
) -> List[Path]:
    """Submit a new PDF or directory of PDFs for processing."""
    raw_dir.mkdir(exist_ok=True)
    build_dir.mkdir(exist_ok=True)

    source = source.expanduser()

    # Copy source to raw directory
    sources = []
    if source.is_file():
        if source != raw_dir / source.name:
            shutil.copy2(source, raw_dir / source.name)
        sources.append(raw_dir / source.name)
    else:
        for filename in glob.glob(str(source)):
            pdf = Path(filename)
            if pdf != raw_dir / pdf.name:
                shutil.copy2(pdf, raw_dir / pdf.name)
            sources.append(raw_dir / pdf.name)

    if sources:
        process_pdf_files(sources, raw_dir, build_dir)

    return sources
