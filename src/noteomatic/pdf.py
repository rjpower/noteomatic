import io
from dataclasses import dataclass
from pathlib import Path
from typing import List

import pypdfium2 as pdfium
from PIL import Image

@dataclass
class ImageData:
    mime_type: str
    content: bytes

@dataclass
class PdfOptions:
    max_resolution: int = 1600
    quality: int = 85

def extract_images_from_pdf(
    pdf_file: Path,
    options: PdfOptions = PdfOptions()
) -> List[ImageData]:
    """Convert PDF pages to image data."""
    image_data_list = []
    pdf = pdfium.PdfDocument(str(pdf_file))
    max_dimension = options.max_resolution

    for page_index in range(len(pdf)):
        page = pdf[page_index]
        bitmap = page.render(scale=300 / 72)
        bitmap = bitmap.to_pil()

        bitmap.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        img_byte_arr = io.BytesIO()
        bitmap.save(img_byte_arr, format="JPEG", quality=options.quality)
        img_byte_arr.seek(0)

        image_data_list.append(
            ImageData(mime_type="image/jpeg", content=img_byte_arr.getvalue())
        )

    return image_data_list
