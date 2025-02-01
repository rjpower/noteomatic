import glob
import logging
import multiprocessing.dummy
import shutil
from pathlib import Path
from typing import List, Optional

from noteomatic.llm import extract_notes, process_article_tags
from noteomatic.notes import save_notes, split_notes
from noteomatic.pdf import PdfOptions, extract_images_from_pdf

logger = logging.getLogger(__name__)


def process_pdf_files(
    sources: List[Path],
    raw_dir: Path,
    build_dir: Path,
    cache_dir: Optional[Path] = None,
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


def extract_from_files(source: Path, raw_dir: Path, build_dir: Path) -> List[Path]:
    """Extract notes from a PDF or directory of PDFs for processing."""
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
