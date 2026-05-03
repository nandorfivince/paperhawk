"""TXT loader — egyszerű plain-text fájlok (eval/teszt szempontjából hasznos)."""

from __future__ import annotations

from graph.states.pipeline_state import IngestedDocument, PageContent


def load_txt(file_name: str, file_bytes: bytes) -> IngestedDocument:
    """Plain text fájl betöltése IngestedDocument-té (UTF-8 dekódolás)."""
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        # Latin-2 fallback magyar szövegekhez
        text = file_bytes.decode("latin-2", errors="replace")

    return IngestedDocument(
        file_name=file_name,
        file_type="txt",
        pages=[PageContent(page_number=1, text=text, is_scanned=False)],
        full_text=text,
        tables_markdown="",
        table_count=0,
        is_scanned=False,
    )
