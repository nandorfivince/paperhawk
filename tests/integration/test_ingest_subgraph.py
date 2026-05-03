"""ingest_subgraph integration tests.

Exercises all three formats (PDF / DOCX / PNG). The nodes are async, so we
invoke via the compiled subgraph's ``ainvoke()``.
"""

from __future__ import annotations

import pytest

from subgraphs.ingest_subgraph import build_ingest_subgraph, ingest_one_doc


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pdf_loader_via_subgraph(sample_pdf_bytes):
    """Load a minimal English invoice PDF."""
    result = await ingest_one_doc("test_invoice.pdf", sample_pdf_bytes)

    assert result is not None
    assert result.ingested is not None

    ing = result.ingested
    assert ing.file_name == "test_invoice.pdf"
    assert ing.file_type == "pdf"
    assert len(ing.pages) >= 1
    assert "INVOICE" in ing.full_text
    assert "AcmeSoft" in ing.full_text
    assert "12-3456789" in ing.full_text
    assert ing.is_scanned is False  # native text was sufficient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_docx_loader_via_subgraph(sample_docx_bytes):
    """DOCX load (always digital)."""
    result = await ingest_one_doc("test_contract.docx", sample_docx_bytes)

    assert result is not None
    assert result.ingested is not None

    ing = result.ingested
    assert ing.file_type == "docx"
    assert ing.is_scanned is False
    assert "Non-Disclosure" in ing.full_text
    assert "SmartSensors" in ing.full_text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_image_loader_vision_first(sample_png_bytes):
    """PNG load via vision-first — image_bytes are always preserved."""
    result = await ingest_one_doc("test_image.png", sample_png_bytes)

    assert result is not None
    assert result.ingested is not None

    ing = result.ingested
    assert ing.file_type == "png"
    assert ing.is_scanned is True  # routed to the vision-extract path
    assert len(ing.pages) == 1
    # image_bytes must be retained for the downstream vision-extract
    assert ing.pages[0].image_bytes is not None
    assert ing.pages[0].image_bytes == sample_png_bytes


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_format_falls_back_to_txt():
    """Unknown suffix → txt loader (best-effort)."""
    result = await ingest_one_doc("strange.xyz", b"plain text content here")
    assert result is not None
    assert result.ingested is not None
    assert result.ingested.file_type == "txt"
    assert "plain text content" in result.ingested.full_text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_subgraph_compiles_directly():
    """The compiled subgraph can be invoked directly."""
    graph = build_ingest_subgraph()
    # Empty input → txt-loader fallback to empty text
    result = await graph.ainvoke({
        "file_name": "empty.txt",
        "file_bytes": b"",
        "started_at": __import__("datetime").datetime.now(),
    })
    assert result.get("ingested") is not None
    assert result["ingested"].full_text == ""
    assert result.get("error") is None
