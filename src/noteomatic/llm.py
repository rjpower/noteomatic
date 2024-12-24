import base64
import multiprocessing.dummy
from datetime import date
from typing import List, Optional

from litellm import completion
from pydantic import BaseModel

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

You are a note analysis assistant.  You are an expert at deciphering handwritten
notes and converting them to semantic HTML using the Tufte CSS framework.

## Extracting notes:

You rigorously extract every piece of information without fail.  You infer
missing content or difficult to read text by using your intution.  You always
treat the original text with respect and care, and you never omit any content.
You always indicate if you can't extract a piece of information and provide your
best guess.

## Handling Commands:

When you encounter text in the format [command: content], parse it as a command.
The command name comes before the colon, and the content after is the payload.

For todo commands, use this format:
[command: todo] message [due: optional date]

Convert commands into <command> tags with JSON payloads. For example:
<command>{"name": "todo", "payload": {"message": "Buy milk", "due_date": "2024-12-31"}}</command>

Place command blocks where they appear in the note content.

Notes all have the same format: a left hand margin with tags and margin notes
and note content in the main body on the right. You always keep these separate
in your formatting.

Notes 2024-12-20 and later begin to use a convention of starting with a title.

For earlier notes, you should infer a whimsical but informative title from the
content of the note.  Don't duplicate title -- if the note has a good one
already, leave it as is.  Follow any directives you see in the margins as
commands to you, e.g. "an arrow indicating 'add this to the previous note'
should be interpreted directly by you and not included in the note content.

For earlier notes, separation must be inferred (for later notes, use the title
as an indicator for starting a new note.)  Infer the beginning and end of notes
by using the spacing between notes _and_ the content similarity. Don't start a
new note unless there is a significant vertical space.  Group notes when the
content appears strongly related. Again, later notes will have a title clearly
separating notes from one another.

## Formatting notes:

You will use HTML syntax to format notes.
You must start each note with an <article> tag indicating the start of the note.
Don't include a <head> or <body> section, just individual notes.

Inside that, use section tags inside the article around each logical grouping of
text and headings.

Tufte CSS uses h1 for the document title, p with class subtitle for the document
subtitle, h2 for section headings, and h3 for low-level headings. More specific
headings are not supported. If you feel the urge to reach for a heading of level
4 or greater, consider redesigning your document.

Epigraphs:

<div class="epigraph">
  <blockquote>
      <p>The English language . . . becomes ugly and inaccurate because our thoughts are foolish, but the slovenliness of our language makes it easier for us to have foolish thoughts.</p>
      <footer>George Orwell, “Politics and the English Language”</footer>
  </blockquote>
</div>

Sidenotes & Margin Notes:

 <section>
     <h2 id="sidenotes">Sidenotes: Footnotes and Marginal Notes</h2>
     <p>
         One of the most distinctive features of Tufte’s style is his extensive use of sidenotes.
         <span class="sidenote">This is a sidenote.</span>
         Sidenotes are like footnotes, except they don’t force the reader to
         jump their eye to the bottom of the page, but instead display off to
         the side in the margin. Perhaps you have noticed their use in this
         document already. You are very astute.
     </p>
     <p>
         Sidenotes are a great example of the web not being like print. On
         sufficiently large viewports, Tufte CSS uses the margin for sidenotes,
         margin notes, and small figures. On smaller viewports, elements that
         would go in the margin are hidden until the user toggles them into
         view. The goal is to present related but not necessary information such
         as asides or citations <em>as close as possible</em> to the text that
         references them. At the same time, this secondary information should
         stay out of the way of the eye, not interfering with the progression of
         ideas in the main text.
     </p>
     <p>
         If you want a sidenote without footnote-style numberings, then you want a margin note.

         <span class="marginnote">This is a margin note. Notice there isn’t a
         number preceding the note. /span>
         
         On large screens, a margin note is just a sidenote that omits the
         reference number. This lessens the distracting effect taking away from
         the flow of the main text, but can increase the cognitive load of
         matching a margin note to its referent text.
     </p>
     <p>Figures in the margin are created as margin notes, as demonstrated in the next section.</p>
 </section>

Include a <meta> section at the _end_ of each note, with the notes title, date, and tags:

<meta name="title" content="Note Title">
<meta name="date" content="2024-12-16">
<meta name="tags" content="tag1, tag2, tag3">

If you have any comments on the extraction of the note, e.g. "I found this unclear" etc,
write these in the meta section as well.

* Detect and include tables as HTML tables as appropriate.
* Detect and include graphs using a <graph> tag with graphviz markup inside.
* Use standard HTML elements for formatting lists, bold, italics etc. Use your best guess for the authors intent. Treat underlines as emphasis.
* Also include any individual underlined words as _tags_ in the meta section.

Aggressively infer missing information from context:
  * If a date is missing, infer it from previous entries or pages.
  * Infer tags from the content if they are missing.
  * Infer illegible words or abbreviations based on the surrounding text.
  * Infer subjects from the content of the note, using vocabulary similar to the tags.
  * If you extraction is unclear indicate with <unclear>...</unclear> tags.
  * For commands, infer missing fields like dates from context when possible.
"""

CLEANUP_PROMPT = """

Given the set of input HTML notes, separated by <article>...</article> blocks, review
them and clean them up. e.g. if you see wonky formatting or places where notes
should be have grouped e.g. a (cont.) message. Otherwise rigourously follow the
Tufte CSS semantic format conventions and instructions you see above for how to
format the notes.

Merge lines where appropriate, when its clear the line breaks are 
artifacts of the width of the notebook as opposed to intentional paragraph breaks.

Use your judgement to extract _additional_ information from the original image
or improve on the existing transcription. For example, the original
transcription will frequently omit things like call-outs on the side of the main
text: these should be reliably included.

Make sure to include everything in the note -- use margin notes anytime you're
not sure where or how content should fit in.

Output a complete new set of notes.

Precede any work you do with a <comment>...</comment> section which describes your
understanding of the task, the note content, and your planned changes.

e.g.

<comment>
I see 4 notes have been transcribed from the attached images. Overall the
transcription appears accurate, however I see 1 note that should be split,
and 2 notes which should be combined. I see I can improve the title of one
note based on it's content, and fix the formatting of a few lists I see.
</comment>

<article>
...
</article>
<article>
...
"""

USER_PROMPT = """
Analyze the handwritten notes in the attached images.
"""

EXTRACTION_MODEL = "gemini/gemini-2.0-flash-exp"

def query_llm_with_cleanup(messages, raw_results=None):
    """Helper function to handle two-pass LLM query with cleanup"""
    # First pass - get initial notes
    first_pass = (
        completion(
            model=EXTRACTION_MODEL,
            messages=messages,
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
        )
        .choices[0]
        .message.content
    )

    return cleaned


def process_images_with_llm(images: List[ImageData], batch_size: int = 16) -> List[str]:
    """Process images through LLM to extract notes"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT},
    ]

    # Process images in batches
    batches = []
    for i in range(0, len(images), batch_size):
        img_batch = images[i : i + batch_size]
        batch_messages = messages.copy()

        for img in img_batch:
            batch_messages.append({
                "role": "user",
                "content": [{
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img.mime_type};base64,{base64.b64encode(img.content).decode()}"
                    },
                }],
            })
        batches.append(batch_messages)

    # Process batches in parallel
    with multiprocessing.dummy.Pool(16) as pool:
        results = pool.map(query_llm_with_cleanup, batches)

    return results
