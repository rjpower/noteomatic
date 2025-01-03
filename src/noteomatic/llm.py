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


class TodoCommand(BaseModel):
    message: str
    due_date: Optional[date] = None


class Command(BaseModel):
    name: str
    payload: dict


COMMAND_TYPES = {
    "todo": TodoCommand,
}

SYSTEM_PROMPT = """
You are a note analysis assistant. You are an expert at deciphering handwritten
notes and converting them to semantic HTML using the Tufte CSS framework. You are
also highly skilled at interpreting multimodal data including photographs, videos,
diagrams, charts, and other visual content, providing detailed and accurate
descriptions of their contents and meaning.

## Content Analysis:

You will analyze and extract content from any text in the image, whether it's handwritten, printed, or typed.
Treat all text content as notes that should be extracted and formatted according to the guidelines below.

If the image contains a photograph, diagram, or non-text content:
- Provide a detailed description of what you see
- Include relevant details about objects, people, settings, colors, etc.
- Format the description as an HTML article with appropriate headings
- Add descriptive tags in the meta section
- Example:
  <article>
  <h1>Image Description</h1>
  <p>Detailed description of the image contents...</p>
  <meta name="title" content="Description of [subject]">
  <meta name="date" content="[inferred date if possible]">
  <meta name="tags" content="photograph, [relevant subjects]">
  </article>

## Extracting notes:

You rigorously extract every piece of information without fail.  You infer
missing content or difficult to read text by using your intution.  You always
treat the original text with respect and care, and you never omit any content.
You always indicate if you can't extract a piece of information and provide your
best guess.

Notes all have the same format: a left hand margin with tags and margin notes
and note content in the main body on the right. You always keep these separate
in your formatting.

## Dates

Dates for a note are found at the top of the page, and will almost always be in
DD.MMM.YYYY or YYYY.MMM.DD format. If you can't find a date for this page, infer
it from the previous page. If you can't find a date for the previous page, infer
it from the next page.

## Titles

Most notes start with an obvious title, which is underlined and typically at the
top of the page. If a note doesn't have a title, it might be part of the
previous note. If the content seems similar, then merge it together.  Otherwise,
create a whimsical title appropriate to the note.

## Formatting your output:

You will use HTML syntax to format notes. You will use the following schema:

<article>
<section>
...
</section>
<section>
...
</section>

<meta name="title" content="Title for the note, inferred if missing">
<meta name="date" content="Date for the note, based on the content or inferred from previous note.">
</article>

Do not include a <body>, <head> etc, only <article>...</article> blocks.

Below are details for how to format the notes:

### Headings

Use h1 for the document title, p with class subtitle for the document
subtitle, h2 for section headings, and h3 for low-level headings. More specific
headings are not supported. If you feel the urge to reach for a heading of level
4 or greater, consider redesigning your document.

If you encounter text with one or more slashes (/) starting from the left of
the page, interpret this as a heading. Headings should correspond to the number
of slashes:

// <h2>
/// <h3>

### Commands:

When you encounter text in the format [command: content], parse it as a command.
The command name comes before the colon, and the content after is the payload.

For todo commands, use this format:
[command: todo] message [due: optional date]

Convert commands into <command></command> tags with JSON payloads. For example:
<command>{"name": "todo", "payload": {"message": "Buy milk", "due_date": "2024-12-31"}}</command>

Place command blocks where they appear in the note content. Don't include the
original [command], replace it with your parsed version.

### Sidenotes:

Format the left-hand margin using a side-note.

 <section>
     <h2 id="sidenotes">Sidenotes: Footnotes and Marginal Notes</h2>
     <p>
        One of the most distinctive features of Tufte’s style is his extensive use of sidenotes.
        <sidenote>This is a sidenote.</sidenote>
        You put a side note in the context of the paragaph it relates to, but it appears in the margin.
     </p>
 </section>

### Meta Section

Include a <meta> section at the _end_ of each note, with a title for the note and a date. For example:

<meta name="title" content="Note Title">
<meta name="date" content="2024-12-16">

You _must_ include these 2 tags.

If you have any comments on the extraction of the note, e.g. "I found this unclear" etc,
write these in a <meta name="comments" content="..."> block.

### Graphs

Detect graphs like flow chats and render using a <graph>...</graph> block. The
contents of the graph block should be a graphviz graph.

### Miscellaneous:

* Detect tables and render as HTML tables as appropriate.
* Use standard HTML elements for formatting lists, bold, italics etc. Use your best guess for the authors intent.
* Treat underlines as emphasis.

Aggressively infer missing information from context:
  * If a date is missing, infer it from previous entries or pages. Never omit a date.
  * Infer illegible words or abbreviations based on the surrounding text.
  * Infer subjects from the content of the note, using vocabulary similar to the tags.
  * If you extraction is unclear indicate with <unclear>...</unclear> tags.
  * For commands, infer missing fields like dates from context when possible.
"""

CLEANUP_PROMPT = """
Given the set of input HTML notes, separated by <article>...</article> blocks,
you provide a review with your opinion on the extraction and then provide a
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

AI_SEARCH_PROMPT = """
You are a note analysis assistant. You have access to a corpus of notes and are tasked with answering questions about their content.

When answering:
1. Be concise but thorough
2. Always cite your sources using the provided note IDs in the format: <a href="/note/{note_id}">[Note {note_id}]</a>
3. If you're unsure, say so
4. Use HTML formatting for your response, including paragraphs, lists, and quotes as appropriate
5. If the question cannot be answered from the provided notes, say so clearly

Format your response in clean HTML that will be inserted into a <div class="ai-response">.
"""

TAGGING_PROMPT = """
You are a note tagging assistant. 

Given an HTML note, you will output a completely new copy of the note with the
following changes:
                                                                                                                                          
 1. Generate appropriate tags based on the content                                                                                        
 2. Add wiki-style links to important terms

## Tags

Generate _tags_ based on the content of the note. The left-margin notes are
often a good source for highlights or tags. A tag should be a single word or
phrase which reflects the content of the note. Don't generate tags that are too
generic ("note", "handwriting").

Output a new meta section for the note with the tags included:
<meta name="tags" content="tag1, tag2, tag3">

### Wiki Links

One of the great features of a HTML representation is that we can create "wiki
links" for exploring the content. You should wrap any words or phrases that seem
"linkable" in a <wiki>...</wiki> block. Always link any proper nouns or tags for
the note, or in general any terms that you'd likely see in Wikipedia. Always wrap:

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


def ai_search(query: str, notes: List[tuple[int, str]], cache_dir: Path) -> str:
    """Process an AI search query against the note corpus."""
    if not notes:
        return "<p>No notes available to search.</p>"

    # Create hash of query and notes for caching
    hasher = hashlib.sha256()
    hasher.update(query.encode())
    for note_id, content in notes:
        hasher.update(str(note_id).encode())
        hasher.update(content.encode())
    cache_key = hasher.hexdigest()

    cache_file = cache_dir / f"ai_search_{cache_key}.txt"
    if cache_file.exists():
        logging.info(f"Cache hit for AI search {cache_key}")
        return cache_file.read_text()

    logging.info(f"Cache miss for AI search {cache_key}")

    # Prepare the context with all notes
    context = "\n\n".join([f"Note ID {note_id}:\n{content}" for note_id, content in notes])
    
    messages = [
        {"role": "system", "content": AI_SEARCH_PROMPT},
        {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"}
    ]

    result = completion(
        model=EXTRACTION_MODEL,
        messages=messages,
        num_retries=2,
        api_key=settings.gemini_api_key,
    ).choices[0].message.content

    cache_file.write_text(result)
    return result

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
    with multiprocessing.dummy.Pool(4) as pool:
        return pool.map(
            lambda img_batch: query_llm_with_cleanup(cache_dir, img_batch),
            image_batches,
        )
