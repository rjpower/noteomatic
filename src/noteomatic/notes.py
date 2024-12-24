import re
import time
from pathlib import Path
from typing import List


def split_notes(note_results: List[str]) -> List[str]:
    """Split concatenated notes into individual notes"""
    notes = []
    for note in note_results:
        if "<comment>" in note:
            comment, note = note.split("</comment>")
            print(comment[9:])

        # split on <article>...</article>
        note = note.split("<article>")[1:]
        for n in note:
            n = n.split("</article>")[0]
            notes.append(n)

    return notes


def _nonce():
    return str(int(time.time() * 1000))


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

        filename = f"{date}_{title}.html"
        (output_dir / filename).write_text(note)
