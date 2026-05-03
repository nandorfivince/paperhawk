"""PDF loader 3-szintű fallback-kel.

Réteg 1: PyMuPDF (fitz) — natív szövegkinyerés. Ha az oldal text >= SCANNED_THRESHOLD
         karakter, ennyi elég, oldal "digitális".

Réteg 2: Tesseract OCR — ha az oldal natív szöveg < SCANNED_THRESHOLD, az oldalt
         renderelt képpé alakítjuk és átadjuk az `ocr_image_bytes`-nak. Ha az
         eredmény >= SCANNED_THRESHOLD, az oldalt is_scanned=False-ra állítjuk
         és az OCR szöveget használjuk.

Réteg 3: Vision fallback — ha az OCR is < SCANNED_THRESHOLD, az oldal `is_scanned=True`
         marad és a `image_bytes` mezőben tartjuk a renderelt képet. A downstream
         extract subgraph `vision_extract_node` közvetlenül a képből (LLM vision)
         nyer ki strukturált adatot.

Mindezt szinkronban csináljuk (PyMuPDF blocking C-binding), de a subgraph-ban
`asyncio.to_thread()` wrapper-rel hívjuk.
"""

from __future__ import annotations

from io import BytesIO

from graph.states.pipeline_state import IngestedDocument, PageContent
from ingest.ocr import SCANNED_THRESHOLD, ocr_image_bytes, tesseract_available
from ingest.tables import extract_tables_markdown


# Render DPI a vision-fallback-hez (200 DPI elég jó minőség Claude vision-nek)
RENDER_DPI = 200


def load_pdf(file_name: str, file_bytes: bytes) -> IngestedDocument:
    """Egy PDF betöltése IngestedDocument-té.

    Args:
        file_name: a fájl neve (a metadata-hoz)
        file_bytes: a PDF bináris tartalma

    Raises:
        Az alsóbb rétegek hibái fel vannak fogva (try/except), de ha a PyMuPDF
        kifejezetten nem tudja megnyitni a fájlt, akkor RuntimeError-ral fail-fast.
    """
    import fitz  # PyMuPDF

    try:
        pdf_doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        raise RuntimeError(f"Nem sikerult megnyitni a PDF-et: {file_name}: {e}") from e

    try:
        pages: list[PageContent] = []
        any_scanned = False
        ocr_enabled = tesseract_available()

        for page_idx, page in enumerate(pdf_doc, start=1):
            # 1. réteg: PyMuPDF natív
            native_text = (page.get_text() or "").strip()

            if len(native_text) >= SCANNED_THRESHOLD:
                # Digitális oldal — natív szöveg elég
                pages.append(PageContent(
                    page_number=page_idx,
                    text=native_text,
                    is_scanned=False,
                    image_bytes=None,
                ))
                continue

            # 2-3. réteg: oldalt képpé renderelünk
            try:
                pix = page.get_pixmap(dpi=RENDER_DPI)
                image_bytes = pix.tobytes("png")
            except Exception:
                # Render fail — natív szöveggel megyünk tovább, mégha kevés is
                pages.append(PageContent(
                    page_number=page_idx,
                    text=native_text,
                    is_scanned=True,  # gyenge minőségű
                    image_bytes=None,
                ))
                any_scanned = True
                continue

            # 2. réteg: Tesseract OCR (ha telepítve van)
            ocr_text = ocr_image_bytes(image_bytes) if ocr_enabled else ""

            if len(ocr_text) >= SCANNED_THRESHOLD:
                # OCR sikerült — a natív szöveg helyett ezt használjuk
                pages.append(PageContent(
                    page_number=page_idx,
                    text=ocr_text,
                    is_scanned=False,
                    image_bytes=image_bytes,  # vision-extract opcionálisan használhatja
                ))
                continue

            # 3. réteg: vision fallback — a downstream extract LLM-vision-nel nyer ki
            pages.append(PageContent(
                page_number=page_idx,
                text=native_text or ocr_text,  # ami van (gyengébb), full_text-be megy RAG-hoz
                is_scanned=True,
                image_bytes=image_bytes,
            ))
            any_scanned = True

        # Aggregált full_text RAG-hoz
        full_text = "\n\n".join(p.text for p in pages if p.text)

        # Táblázatok kinyerése pdfplumber-rel (ha van)
        tables_md, table_count = extract_tables_markdown(file_bytes)

        return IngestedDocument(
            file_name=file_name,
            file_type="pdf",
            pages=pages,
            full_text=full_text,
            tables_markdown=tables_md,
            table_count=table_count,
            is_scanned=any_scanned,
        )
    finally:
        pdf_doc.close()
