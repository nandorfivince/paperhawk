"""Táblázat-kinyerés PDF-ből — pdfplumber → Markdown.

Minden táblázat egy egyszerű Markdown formátumban kerül a `IngestedDocument.tables_markdown`
mezőbe. A downstream extract subgraph ezeket kombinálva használja a `full_text`-tel
(tables külön szövegrészben → LLM-prompt szegmentálva).
"""

from __future__ import annotations

from io import BytesIO


def extract_tables_markdown(pdf_bytes: bytes) -> tuple[str, int]:
    """Visszaadja a (markdown_szöveg, tábla_száma) tuple-t.

    Lazy-import: a pdfplumber package csak akkor szükséges, ha PDF-et dolgozunk fel.

    Hibatűrő: ha a pdfplumber elesik vagy nincs telepítve, üres ("", 0)-t ad
    — a full_text nélküle is indexelhető.
    """
    try:
        import pdfplumber
    except ImportError:
        return "", 0

    table_blocks: list[str] = []
    table_count = 0

    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables() or []
                for tbl_idx, table in enumerate(tables, start=1):
                    if not table or not any(table):
                        continue
                    md = _table_to_markdown(table)
                    if md.strip():
                        table_blocks.append(
                            f"### Táblázat (oldal {page_idx}, #{tbl_idx})\n\n{md}\n"
                        )
                        table_count += 1
    except Exception:
        # PDF malformed vagy pdfplumber bug — visszaadjuk amit kinyertünk eddig
        pass

    return "\n".join(table_blocks), table_count


def _table_to_markdown(table: list[list[str | None]]) -> str:
    """2D listából Markdown tábla. Az első sor a fejléc."""
    if not table:
        return ""

    # Cellákat normalizáljuk (None → ""), whitespace tisztítás
    rows = [[(cell or "").strip().replace("\n", " ") for cell in row] for row in table]

    # Üres sorok kiszűrése
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return ""

    # Header + separator + data
    header = rows[0]
    n_cols = len(header)
    if n_cols == 0:
        return ""

    sep = ["---"] * n_cols
    data = rows[1:] if len(rows) > 1 else []

    # Cellák szélességéhez padding-ot adunk az olvashatóságért (max 30 char)
    def fmt_row(row: list[str]) -> str:
        return "| " + " | ".join((c[:30] if c else "") for c in row) + " |"

    lines = [fmt_row(header), fmt_row(sep)]
    for r in data:
        # Ha a sor rövidebb mint a header, padd-eljük üresekkel
        padded = list(r) + [""] * (n_cols - len(r))
        lines.append(fmt_row(padded[:n_cols]))

    return "\n".join(lines)
