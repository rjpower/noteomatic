import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List

import pypdfium2 as pdfium
from PIL import Image


@dataclass
class ImageData:
    mime_type: str
    content: bytes

# Gemini processes tiles of 768x768 pixels, so we want to ensure that that our
# A5 paper divides these evenly. This should result in dimension of 768*2 on our
# short edge, and 768*~1.41 on our long edge.

@dataclass
class PdfOptions:
    short_dimension: int = 768 * 2
    quality: int = 85

def extract_images_from_pdf(
    pdf_file: Path,
    options: PdfOptions = PdfOptions()
) -> List[ImageData]:
    """Convert PDF pages to image data."""
    image_data_list = []
    pdf = pdfium.PdfDocument(str(pdf_file))

    for page_index in range(len(pdf)):
        page = pdf[page_index]
        bitmap = page.render(scale=300 / 72)
        bitmap = bitmap.to_pil()

        # compute the long dimension, assuming the short_dimension is 768*2
        long_dimension = int(bitmap.height * options.short_dimension / bitmap.width)
        bitmap = bitmap.resize((options.short_dimension, long_dimension), Image.LANCZOS)
        logging.info("Computed bitmap, new dimensions: %s", bitmap.size)

        img_byte_arr = io.BytesIO()
        bitmap.save(img_byte_arr, format="JPEG", quality=options.quality)
        img_byte_arr.seek(0)

        image_data_list.append(
            ImageData(mime_type="image/jpeg", content=img_byte_arr.getvalue())
        )

    return image_data_list
