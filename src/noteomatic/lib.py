import logging
import pickle
from pathlib import Path
from typing import List

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from noteomatic.llm import process_images_with_llm
from noteomatic.notes import save_notes, split_notes
from noteomatic.pdf import extract_images_from_pdf

logger = logging.getLogger(__name__)

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
            try:
                creds = flow.run_local_server(port=0)
            except webbrowser.Error:
                auth_url, _ = flow.authorization_url(prompt='consent')
                print(auth_url)
                auth_code = input("Enter the authorization code: ")
                creds = flow.fetch_token(code=auth_code)

        
        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)

    return build('drive', 'v3', credentials=creds)

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
        logger.info(f"Extracted {len(images)} images from {pdf_file}")

        # Process with LLM
        results = process_images_with_llm(images)

        # Save notes
        notes = split_notes(results)
        save_notes(notes, notes_dir)

        logger.info(f"Processed {pdf_file} -> {len(notes)} notes")
