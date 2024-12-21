import re
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


def save_notes(notes: List[str], output_dir: Path):
    """Save processed notes as individual HTML files"""
    for note in notes:
        title = re.search(r'<meta name="title" content="(.*?)">', note).group(1)
        date = re.search(r'<meta name="date" content="(.*?)">', note).group(1)

        filename = f"{date}_{title}.html"
        (output_dir / filename).write_text(note)
