"""Kép loader (PNG/JPG/JPEG) -- vision-first, NEM OCR az extract-hez.

Filozófia: a képeknél (NEM PDF) az LLM közvetlenül a képet látja, NEM az OCR
szövegéből dolgozik. Az OCR csak a `full_text` mezőhöz / RAG keresőhöz fut le
(opcionálisan).

Tehát:
  * PageContent.image_bytes = a kép bináris tartalma (vision-extract használja)
  * PageContent.is_scanned = True (vision-extract pathra megy)
  * full_text = OCR text (ha van) vagy üres -- chunker majd kihagyhatja

Ez a `prototype-agentic` `pdf.py:load_image` mintát követi (vision-first elv).
"""

from __future__ import annotations

from graph.states.pipeline_state import IngestedDocument, PageContent
from ingest.ocr import ocr_image_bytes, tesseract_available


def load_image(file_name: str, file_bytes: bytes, file_type: str = "png") -> IngestedDocument:
    """Egy kép betöltése IngestedDocument-té (mindig vision-first).

    file_type: `png`, `jpg`, `jpeg` — csak metadata, nem befolyásolja a feldolgozást.
    """
    # OCR opcionálisan a full_text-hez (RAG kereséshez hasznos)
    full_text = ""
    if tesseract_available():
        full_text = ocr_image_bytes(file_bytes)

    page = PageContent(
        page_number=1,
        text=full_text,
        is_scanned=True,  # vision-extract path
        image_bytes=file_bytes,
    )

    return IngestedDocument(
        file_name=file_name,
        file_type=file_type,
        pages=[page],
        full_text=full_text,
        tables_markdown="",
        table_count=0,
        is_scanned=True,
    )
