import logging
import re
import time
from pathlib import Path
from typing import List


def _nonce():
    return str(int(time.time() * 1000))


def split_notes(note_result: str) -> List[str]:
    """Split concatenated notes into individual notes"""
    if "<comment>" in note_result:
        comment, note = note_result.split("</comment>")
        logging.info("Comment from the LLM %s", comment[9:])

    # split on <article>...</article>
    notes = []
    articles = note_result.split("<article>")[1:]
    for article in articles:
        article = article.split("</article>")[0]
        notes.append(article)
    return notes


def save_notes(notes: List[str], output_dir: Path):
    """Save processed notes as individual HTML files"""
    for i, note in enumerate(notes):
        title_match = re.search(r'<meta name="title" content="(.*?)">', note)
        date_match = re.search(r'<meta name="date" content="(.*?)">', note)

        if title_match:
            title = title_match.group(1)
        else:
            title = f"untitled-note-{_nonce()}-{i}"

        if date_match:
            date = date_match.group(1)
        else:
            date = time.strftime("%Y-%m-%d")

        logging.info("Saving note %d - %s", i, title)

        filename = f"{date}_{title}.html"
        (output_dir / filename).write_text(note)
