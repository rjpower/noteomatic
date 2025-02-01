import base64
import hashlib
import logging
import multiprocessing.dummy
from datetime import date
from pathlib import Path
from typing import List, Optional

from litellm import completion
from pydantic import BaseModel

from .config import settings
from .pdf import ImageData

SYSTEM_PROMPT = """
<INSTRUCTIONS>
You are an expert at handwritten note analysis and extraction. You interpret handwritten notes and convert
them into Markdown with Tufte‐style enhancements. You must extract every piece
of information carefully, inferring missing or unclear parts as needed, and
explicitly marking uncertainties with `<unclear>…</unclear>`.

## Extracting Notes
Each note has two regions:
- A left margin for tags, marginalia, and sidenotes.
- A main body with the core content.

Preserve them separately in your output:
- Place marginal/left‐hand content as a sidenote or margin note (see “Sidenotes” below).
- Place the main body text inline.

## Dates
Notes typically show a date at the top in `DD.MMM.YYYY` or `YYYY.MMM.DD`. If no
date appears, infer it from previous or subsequent notes. Never omit a date.

## Titles
Most notes start with an obvious title near the top. 
1. If a title is present, use it.
2. If not, see if the content is continuing the previous note:
   - If it looks like a continuation, merge it into that note.
   - Otherwise, invent an appropriate “whimsical” title.

# Creating a Document

You will emit one or more notes, each using Markdown syntax, with the following structure:

1. All notes are wrapped in `<article>...</article>` tags. 
2. An title for the note (using `# `).
3. Body text and sections as needed.
4. Sidenotes annotations for the left‐hand margin content.
5. A metadata block using YAML front matter

## Headings

	•	Use # for the note’s main title.
	•	Use ## for top‐level sections.
	•	Use ### for lower‐level sections.
	•	Do not create headings deeper than ###.

If you see text beginning with slashes, convert them to headings:
	•	// → Convert to ##
	•	/// → Convert to ###
    
## Margins and Sidenotes

Convert annotations in the margin into inline footnotes. For example:

Here is some text.^[Is is text from the margin.]

## Graphs

When you detect a graph (e.g., a flowchart), wrap its Graphviz code in a fenced
block labeled “dot”:

```dot
digraph example {
  A -> B;
  B -> C;
}
```

## Inferring and Marking Unclear Content
- Always infer missing or illegible text if plausible.
- If truly uncertain, wrap it in `<unclear>…</unclear>`.

### Miscellaneous:

* Detect tables and render using Markdown table syntax.
* Use standard elements for formatting lists, bold, italics etc. Use your best guess for the authors intent.
* Treat underlines as emphasis.
* If a date is missing, infer it from previous entries or pages. Never omit a date.
* Include all text you see, never elide or attempt to abbreviate any output.

# Example output:
<article>
---
title: "My Note Title"
date: "2025-01-31"
comments: "Overall the note was legible. I marked a few sections as unclear."
---

# My Amazing Note

I was writing a note the other day about writing notes and suddenly found myself
spiraling into a deep <unclear>cavern</unclear>.

## The Cavern

At the bottom of the cavern was a mysterious symbol^[more mysterious because it
was in a dark cavern!]. I became very afraid, so I made a diagram of the symbol:

```dot
digraph symbol {
  Cat -> Dog
  Dog -> Giraffe
  Dog -> Human
  Giraffe -> Human
}
```
What could it mean? Was this the mark of the well-known #giraffe cult?
...
</article>
<article>... content of the next note ... </article>
</INSTRUCTIONS>
"""

CLEANUP_PROMPT = """
Given the set of input Markdown notes, separated by <article>...</article> blocks,
provide a review with your opinion on the extraction and then provide a
new set of cleaned notes. You should follow these guidelines:

* If you see odd or incorrect formatting, fix it.
* If you see two notes that should be have grouped (based on the content or a cont./continue annotation), merge them.
* A note should never start with (cont.) or (continued.). Unless this is the first image in your series, you must merge this note with the previous note.
* Ensure notes rigorously follow the format conventions and instructions you see above for how to format the notes.
* Merge lines where appropriate, when its clear the line breaks are artifacts of the width of the notebook as opposed to intentional paragraph breaks.

Use your judgement to extract additional information from the original image or
improve on the existing transcription. The original transcription will
frequently omit things like margin notes on the side of the main text: these
should be reliably included.

Make sure to include everything in the note -- use <unclear>...</unclear> when
you're not sure where or how content should fit in.

Precede any work you do with a <comment>...</comment> section which describes your
understanding of the task, the note content, and your planned changes.

Output a complete new set of notes.

Example output:

<comment>
I see 4 notes have been transcribed from the attached images. Overall the
transcription appears accurate, however I see 1 note that should be split into
2, and 2 notes which should be combined. I see I can improve the title of one
note based on it's content, and fix the formatting of a few lists I see.
</comment>

<article>
...
</article>
<article>
...
</article>
...
"""

USER_PROMPT = """
Analyze the handwritten notes in the attached images.
"""

TAGGING_PROMPT = """
You are a note tagging assistant. 

Given a Markdown note, you will output a completely new copy of the note with the
following changes:
                                                                                                                                          
 1. Generate appropriate tags based on the content
 2. Add wiki-style links to important terms

## Tags

Generate _tags_ based on the content of the note. The left-margin notes are
often a good source for highlights or tags. A tag should be a single word or
phrase which reflects the content of the note. Don't generate tags that are too
generic ("note", "handwriting").

Emit tags in the front-matter for the note. E.g. if the note was about a Giraffe
cult which threatened to take over the world, you might generate front-matter
like:

---
title: "Finding the Elusive Giraffe Cult"
date: "2025-01-31"
comments: "Overall the note was legible. I marked a few sections as unclear."
tags:
    - giraffe
    - cult
    - takeover
---

### Linking Terms

You should wrap any words or phrases that seem "linkable" in a local link
([[Link]]) block block. Always link any proper nouns or tags for the note, or in
general any terms that you'd likely see in Wikipedia. Always wrap:

 - Proper nouns                                                                                                                           
 - Technical terms                                                                                                                        
 - Concepts that could have their own Wikipedia article                                                                                   
 - Any terms that appear in the tags       

Remember to generate a completely new <article> with the tags and wiki links.
"""

EXTRACTION_MODEL = "gemini/gemini-2.0-flash-exp"


def _hash_images(images: List[ImageData]) -> str:
    """Create a deterministic hash for a batch of images"""
    hasher = hashlib.sha256()
    for img in sorted(images, key=lambda x: x.mime_type):
        hasher.update(img.content)
        hasher.update(img.mime_type.encode())
    return hasher.hexdigest()


def _make_initial_request(images: List[ImageData]) -> List[dict]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT},
    ]

    # Add all images for this batch in one message
    image_contents = []
    for img in images:
        image_contents.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{img.mime_type};base64,{base64.b64encode(img.content).decode()}"
                },
            }
        )

    messages.append({"role": "user", "content": image_contents})
    return messages


def query_llm_with_cleanup(cache_dir: Path, img_batch: List[ImageData]):
    """Helper function to handle two-pass LLM query with cleanup"""
    cache_key = _hash_images(img_batch)
    cache_file = cache_dir / f"{cache_key}.txt"

    if cache_file.exists():
        logging.info(f"Cache hit for {cache_key}")
        return cache_file.read_text()

    logging.info(f"Cache miss for {cache_key}")

    messages = _make_initial_request(img_batch)

    # First pass - get initial notes
    first_pass = (
        completion(
            model=EXTRACTION_MODEL,
            messages=messages,
            num_retries=2,
            api_key=settings.gemini_api_key,
        )
        .choices[0]
        .message.content
    )

    # Second pass - cleanup with original results
    cleanup_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": first_pass},
        {"role": "user", "content": CLEANUP_PROMPT},
    ]

    cleaned = (
        completion(
            model=EXTRACTION_MODEL,
            messages=cleanup_messages,
            num_retries=2,
            api_key=settings.gemini_api_key,
        )
        .choices[0]
        .message.content
    )

    if cache_dir:
        cache_file.write_text(cleaned)

    return cleaned


def process_article_tags(article: str, cache_dir: Path) -> str:
    """Process a single article to add tags and wiki links"""
    if not article.strip():
        return article

    # Create hash of article content for caching
    article_hash = hashlib.sha256(article.encode()).hexdigest()
    cache_file = cache_dir / f"tags_{article_hash}.txt"
    if cache_file.exists():
        logging.info(f"Cache hit for {article_hash}")
        return cache_file.read_text()

    logging.info(f"Cache miss for {article_hash}")

    messages = [
        {"role": "system", "content": TAGGING_PROMPT},
        {"role": "user", "content": article},
    ]

    result = (
        completion(
            model=EXTRACTION_MODEL,
            messages=messages,
            num_retries=2,
            api_key=settings.gemini_api_key,
        )
        .choices[0]
        .message.content
    )

    cache_file.write_text(result)
    return result


def extract_notes(
    images: List[ImageData], batch_size: int = 16, cache_dir: Optional[Path] = None
) -> List[str]:
    """Process images through LLM to extract notes"""
    logging.info("Processing %d images in batches of %d", len(images), batch_size)

    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)

    # First pass: Extract notes from images
    image_batches = [
        images[i : i + batch_size] for i in range(0, len(images), batch_size)
    ]
    with multiprocessing.dummy.Pool(1) as pool:
        return pool.map(
            lambda img_batch: query_llm_with_cleanup(cache_dir, img_batch),
            image_batches,
        )
