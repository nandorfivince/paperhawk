"""pipeline_graph end-to-end smoke test (dummy LLM mode).

Walks one PDF through ingest → classify → extract → rag-index → quote-validate
→ compare → risk → report. Verifies that:
  * the documents list is populated
  * the risks list contains at least a basic or domain rule finding
  * report.performance.speedup > 1.0 (real speedup vs the manual estimate)
"""

from __future__ import annotations

import pytest

from store import HybridStore


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_e2e_single_invoice(sample_pdf_bytes, tmp_path):
    from graph.pipeline_graph import build_pipeline_graph

    store = HybridStore(
        chroma_path=str(tmp_path / "chroma"),
        collection_name="test_pipeline_invoice",
    )
    graph = build_pipeline_graph(store)

    state = await graph.ainvoke({
        "files": [("invoice_january.pdf", sample_pdf_bytes)],
    })

    documents = state.get("documents") or []
    assert len(documents) == 1, "Single uploaded PDF → 1 ProcessedDocument"

    pd = documents[0]
    assert pd.ingested is not None
    assert pd.classification is not None
    assert pd.classification.doc_type == "invoice"
    assert pd.extracted is not None
    assert pd.extracted.raw.get("invoice_number") == "2026/001"

    # RAG indexed
    assert pd.rag_chunks_indexed >= 1
    assert store.chunk_count >= 1

    # Risks
    risks = state.get("risks") or []
    # ISA 500 evidence score is UI-only (not in risks). Materiality (ISA 320)
    # is an info-level risk that lands in the list.
    assert any(r.source_check_id == "check_07_materiality" for r in risks)

    # Report
    report = state.get("report")
    assert report is not None
    assert report["document_count"] == 1
    assert report["performance"]["documents"] == 1
    assert report["performance"]["manual_estimate_minutes"] > 0
    # Speedup > 1 (8 minutes manual → < 8*60 sec automated)
    assert report["performance"]["speedup"] > 1.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_three_doc_compare(sample_pdf_bytes, tmp_path):
    """3 docs (invoice + delivery_note + purchase_order) → three-way matching."""
    from graph.pipeline_graph import build_pipeline_graph

    # Same PDF reused 3× with different filenames + classifier picks via name prefix
    store = HybridStore(
        chroma_path=str(tmp_path / "chroma_three"),
        collection_name="test_three_way",
    )
    graph = build_pipeline_graph(store)

    state = await graph.ainvoke({
        "files": [
            ("invoice_construction.pdf", sample_pdf_bytes),
            ("delivery_note_construction.pdf", sample_pdf_bytes),
            ("purchase_order_construction.pdf", sample_pdf_bytes),
        ],
    })

    documents = state.get("documents") or []
    assert len(documents) == 3

    # Classifier splits types based on filename prefixes
    types = {d.classification.doc_type for d in documents if d.classification}
    assert "invoice" in types
    assert "delivery_note" in types
    assert "purchase_order" in types


@pytest.mark.integration
@pytest.mark.asyncio
async def test_risk_subgraph_runs_on_minimal_input(tmp_path):
    """The risk subgraph runs end-to-end on minimal extracted data without crashing."""
    from datetime import datetime

    from graph.states.pipeline_state import (
        Classification,
        ExtractedData,
        IngestedDocument,
        PageContent,
        ProcessedDocument,
    )
    from subgraphs.risk_subgraph import build_risk_subgraph

    ingested = IngestedDocument(
        file_name="incomplete_invoice.pdf",
        file_type="pdf",
        pages=[PageContent(page_number=1, text="Incomplete invoice — partial text only")],
        full_text="Incomplete invoice — partial text only",
    )
    classification = Classification(
        doc_type="invoice",
        doc_type_display="Invoice",
        confidence=0.5,
        language="en",
        used_vision=False,
    )
    extracted = ExtractedData(
        raw={"_quotes": [], "_confidence": {}},
        _quotes=[],
        _confidence={},
    )
    pd = ProcessedDocument(
        ingested=ingested,
        classification=classification,
        extracted=extracted,
    )

    risk_graph = build_risk_subgraph()
    state_in = {
        "documents": [pd],
        "risks": [],
        "started_at": datetime.now(),
        "processing_seconds": 0.0,
    }
    out = await risk_graph.ainvoke(state_in)
    risks = out.get("risks") or []
    # Subgraph runs without error; risks may or may not include items
    # depending on the dummy classifier path. We just assert it returned a list.
    assert isinstance(risks, list)
