"""Chunking — természetes vágási pontok.

A `prototype-agentic` mintát követjük (chunking.py:27-76):
  * SINGLE_CALL_THRESHOLD = 30000 char → nem darabolunk (egy LLM hívás elég)
  * default 15K char chunk + 500 char overlap
  * vágási preferencia: \\n\\n (bekezdés) > '. ' (mondat) > '\\n' > szóköz

A chunk-ok metadata-jában tárolódik a forrás dokumentum neve és a chunk_index.
"""

from __future__ import annotations

from typing import Any

from config import settings


def needs_chunking(text: str) -> bool:
    """Eldönti, hogy a szöveg hosszabb-e mint a SINGLE_CALL_THRESHOLD."""
    return len(text or "") > settings.single_call_threshold


def chunk_text(
    text: str,
    max_chars: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """Egy szöveget chunk-okra darabol természetes vágási pontoknál.

    Default: settings.chunk_max_chars (15_000) + settings.chunk_overlap_chars (500).
    """
    max_chars = max_chars or settings.chunk_max_chars
    overlap = overlap or settings.chunk_overlap_chars

    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    pos = 0
    n = len(text)

    while pos < n:
        end = pos + max_chars
        if end >= n:
            chunks.append(text[pos:n])
            break

        # Természetes vágási pont keresése a [pos + max_chars - 500, pos + max_chars] tartományban
        cut = _find_natural_cut(text, pos + max_chars - overlap, end)
        chunks.append(text[pos:cut])
        # Overlap: a következő chunk a cut - overlap-tól kezdődik (ha értelmes)
        pos = max(cut - overlap, pos + 1)
        if pos >= n - 1:
            break

    return chunks


def _find_natural_cut(text: str, min_pos: int, max_pos: int) -> int:
    """A [min_pos, max_pos] tartományban keres egy természetes vágási pontot.

    Preferencia sorrend: bekezdés-vég, mondat-vég, sortörés, szóköz.
    Ha egyik sem talál → max_pos (kemény vágás).
    """
    window = text[min_pos:max_pos]
    if not window:
        return max_pos

    # 1. Bekezdés-vég: \n\n
    idx = window.rfind("\n\n")
    if idx >= 0:
        return min_pos + idx + 2

    # 2. Mondat-vég: '. ', '! ', '? '
    for marker in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
        idx = window.rfind(marker)
        if idx >= 0:
            return min_pos + idx + len(marker)

    # 3. Sortörés
    idx = window.rfind("\n")
    if idx >= 0:
        return min_pos + idx + 1

    # 4. Szóköz
    idx = window.rfind(" ")
    if idx >= 0:
        return min_pos + idx + 1

    # 5. Kemény vágás
    return max_pos


def chunk_document(
    file_name: str,
    full_text: str,
    doc_type: str | None = None,
) -> list[dict[str, Any]]:
    """Dokumentumot chunk-listára bont, metadata-val a vector store-hoz.

    Returns:
        [{"text": str, "metadata": {"source": ..., "doc_type": ..., "chunk_index": int}}, ...]

    Ha a `full_text` < SINGLE_CALL_THRESHOLD, egyetlen chunk lesz.
    """
    chunks_text = chunk_text(full_text)
    return [
        {
            "text": chunk,
            "metadata": {
                "source": file_name,
                "doc_type": doc_type or "egyeb",
                "chunk_index": idx,
            },
        }
        for idx, chunk in enumerate(chunks_text)
    ]
