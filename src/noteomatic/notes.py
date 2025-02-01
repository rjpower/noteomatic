import hashlib
import logging
import re
import time
from ast import parse
from pathlib import Path
from typing import Dict, List

import yaml


def note_hash(content: str) -> str:
    """Generate a consistent hash for note saving/sharing."""
    return hashlib.md5(content.encode()).hexdigest()[:8]


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


def parse_note(raw_content: str):
    """Parse note metadata from markdown or note content hints."""
    content = raw_content.strip()

    # Remove article tags and markdown code blocks
    content = re.sub(r"</?article>", "", content).strip()
    content = content.strip().removeprefix("```markdown").removesuffix("```")

    # Try to parse existing front-matter
    if content.strip().startswith("---"):
        _, front, content = content.split("---", 3)

    front_matter: Dict[str, str] = yaml.safe_load(front)
    if "title" not in front_matter:
        front_matter["title"] = f"untitled-{note_hash(raw_content)}"
    if "date" not in front_matter:
        front_matter["date"] = time.strftime("%Y-%m-%d")

    return front_matter, content


def save_notes(notes: List[str], output_dir: Path):
    """Save processed notes as individual markdown files with front-matter"""
    for i, note in enumerate(notes):
        front_matter, content = parse_note(note)
        final_content = "---\n"
        final_content += yaml.dump(front_matter, default_flow_style=False)
        final_content += "---\n\n"
        final_content += content.strip()

        filename = f"{front_matter['date']}_{front_matter['title']}.md"
        logging.info("Saving note: %s", filename)
        (output_dir / filename).write_text(final_content)
