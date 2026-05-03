"""Integration tests for classify, extract, and RAG-index in dummy mode."""

from __future__ import annotations

import pytest

from graph.states.pipeline_state import IngestedDocument, PageContent
from nodes.extract._dummy_extractor import extract_dummy
from nodes.extract.quote_validator_node import quote_validator_node
from nodes.pipeline.classify_node import classify_node
from schemas import flatten_universal, load_schema, pydantic_for
from subgraphs.extract_subgraph import build_extract_subgraph


# ---------------------------------------------------------------------------
# Schema / Pydantic
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_all_schemas():
    """All 6 schemas load."""
    for doc_type in ("invoice", "delivery_note", "purchase_order", "contract",
                     "financial_report", "other"):
        s = load_schema(doc_type)
        assert s["type"] == "object"
        assert "_quotes" in s["required"]
        assert "_confidence" in s["required"]


@pytest.mark.unit
def test_pydantic_mirrors():
    from schemas.pydantic_models import (
        ContractModel,
        DeliveryNoteModel,
        FinancialReportModel,
        InvoiceModel,
        PurchaseOrderModel,
        UniversalModel,
    )

    assert pydantic_for("invoice") is InvoiceModel
    assert pydantic_for("delivery_note") is DeliveryNoteModel
    assert pydantic_for("purchase_order") is PurchaseOrderModel
    assert pydantic_for("contract") is ContractModel
    assert pydantic_for("financial_report") is FinancialReportModel
    assert pydantic_for("other") is UniversalModel
    assert pydantic_for("unknown") is UniversalModel  # fallback


@pytest.mark.unit
def test_invoice_pydantic_validation():
    from schemas.pydantic_models import InvoiceModel
    inv = InvoiceModel.model_validate({
        "invoice_number": "2026/001",
        "issuer": {"name": "Acme Inc.", "tax_id": "12-3456789"},
        "customer": {"name": "Beta LLC", "tax_id": "98-7654321"},
        "total_net": 20_000.00,
        "total_vat": 4_000.00,
        "total_gross": 24_000.00,
        "_quotes": ["Invoice number: 2026/001"],
        "_confidence": {"invoice_number": "high"},
    })
    assert inv.invoice_number == "2026/001"
    assert inv.issuer is not None
    assert inv.issuer.tax_id == "12-3456789"
    assert inv.total_gross == 24_000.00


# ---------------------------------------------------------------------------
# Dummy extractor (regex)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_dummy_extract_invoice():
    text = (
        "INVOICE\n\n"
        "Invoice number: 2026/001\n"
        "Issue date: 2026-01-31\n"
        "Fulfillment date: 2026-01-30\n"
        "Payment due: 2026-02-29\n\n"
        "Issuer: AcmeSoft Inc.\n"
        "Tax ID: 12-3456789\n\n"
        "Customer: BudaData LLC\n"
        "Tax ID: 98-7654321\n\n"
        "Total net: $20,000.00\n"
        "Total VAT: $4,000.00\n"
        "Total gross: $24,000.00\n"
    )
    out = extract_dummy(text, "invoice", "invoice_january.pdf")

    assert out["invoice_number"] == "2026/001"
    assert out["issue_date"] == "2026-01-31"
    assert out["payment_due_date"] == "2026-02-29"
    assert len(out.get("_quotes", [])) > 0


@pytest.mark.unit
def test_dummy_extract_contract():
    text = (
        "Non-Disclosure Agreement (NDA)\n\n"
        "Parties: SmartSensors Inc. (tax id: 13-5792468) "
        "and InfoTech Ltd. (tax id: 86-4201357)\n\n"
        "Effective date: 2026-01-15\n"
        "Expiry date: 2027-01-15\n\n"
        "Penalty: A breach triggers a $50,000 penalty per incident.\n"
        "Governing law: State of Delaware, USA.\n"
    )
    out = extract_dummy(text, "contract", "nda_smartsensors.pdf")

    assert out["contract_type"] == "NDA"
    assert out.get("effective_date") == "2026-01-15"
    assert out.get("expiry_date") == "2027-01-15"
    assert out.get("confidentiality_clause") is True
    # governing_law detection (multilingual) — "Delaware" or fallback
    assert "delaware" in (out.get("governing_law", "") or "").lower() or out.get("governing_law")


# ---------------------------------------------------------------------------
# flatten_universal
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_flatten_universal_keeps_flat_dict_unchanged():
    """A typed-shape dict (no universal indicators) passes through."""
    flat = {"invoice_number": "X", "_quotes": []}
    out = flatten_universal(flat, "invoice")
    assert out["invoice_number"] == "X"


@pytest.mark.unit
def test_flatten_universal_unfolds_nested():
    """Universal → flat: dates, amounts, parties get unfolded."""
    universal = {
        "document_number": "X-001",
        "document_type": "contract",
        "dates": {"effective": "2026-01-01", "expiry": "2027-01-01"},
        "amounts": {"total_net": 100, "total_vat": 27, "total_gross": 127, "currency": "USD"},
        "parties": [
            {"name": "A Inc.", "role": "supplier", "tax_id": "11-1111111"},
            {"name": "B Corp.", "role": "customer", "tax_id": "22-2222222"},
        ],
        "_quotes": ["source1"],
        "_confidence": {"X": "high"},
    }
    out = flatten_universal(universal, "contract")
    assert out["invoice_number"] == "X-001"
    assert out["effective_date"] == "2026-01-01"
    assert out["total_net"] == 100
    assert out["issuer"]["name"] == "A Inc."
    assert out["customer"]["name"] == "B Corp."


# ---------------------------------------------------------------------------
# classify_node + extract_node async
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_classify_node_invoice():
    ingested = IngestedDocument(
        file_name="invoice_january.pdf",
        file_type="pdf",
        pages=[PageContent(page_number=1, text="INVOICE\nInvoice number: X")],
        full_text="INVOICE\nInvoice number: X",
    )
    out = await classify_node({"ingested": ingested})
    assert "documents" in out
    pd = out["documents"][0]
    assert pd.classification.doc_type == "invoice"
    # Language detection: "Invoice" + small text → may default to en
    assert pd.classification.language in ("en", "hu", "de")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_extract_subgraph_invoice(sample_pdf_bytes):
    """End-to-end: ingest → classify → extract."""
    from subgraphs.ingest_subgraph import ingest_one_doc

    pd = await ingest_one_doc("invoice_test.pdf", sample_pdf_bytes)
    assert pd is not None

    cls_out = await classify_node({"ingested": pd.ingested})
    classification = cls_out["documents"][0].classification

    extract_graph = build_extract_subgraph()
    ext_out = await extract_graph.ainvoke({
        "ingested": pd.ingested,
        "classification": classification,
    })
    pd_with_extracted = ext_out["documents"][0]
    assert pd_with_extracted.extracted is not None
    raw = pd_with_extracted.extracted.raw
    assert raw.get("invoice_number") == "2026/001"


# ---------------------------------------------------------------------------
# quote_validator_node
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quote_validator_passes_valid_quotes():
    from graph.states.pipeline_state import ExtractedData, ProcessedDocument

    ingested = IngestedDocument(
        file_name="X.pdf",
        file_type="pdf",
        pages=[PageContent(page_number=1, text="Invoice number: 2026/001 Penalty: $50,000")],
        full_text="Invoice number: 2026/001 Penalty: $50,000",
    )
    extracted = ExtractedData(
        raw={
            "_quotes": ["Invoice number: 2026/001", "Penalty: $50,000"],
            "_confidence": {"X": "high"},
        },
        _quotes=["Invoice number: 2026/001", "Penalty: $50,000"],
        _confidence={"X": "high"},
    )
    pd = ProcessedDocument(ingested=ingested, extracted=extracted)
    out = await quote_validator_node({"documents": [pd]})
    # All quotes valid → no new risks
    assert out.get("risks") in (None, [])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quote_validator_flags_invalid_quotes():
    from graph.states.pipeline_state import ExtractedData, ProcessedDocument

    ingested = IngestedDocument(
        file_name="X.pdf",
        file_type="pdf",
        pages=[PageContent(page_number=1, text="Just this short text is here.")],
        full_text="Just this short text is here.",
    )
    extracted = ExtractedData(
        raw={
            "_quotes": ["Hallucinated quote that is not in the source"],
            "_confidence": {"X": "high"},
        },
        _quotes=["Hallucinated quote that is not in the source"],
        _confidence={"X": "high"},
    )
    pd = ProcessedDocument(ingested=ingested, extracted=extracted)
    out = await quote_validator_node({"documents": [pd]})
    assert "risks" in out
    assert len(out["risks"]) == 1
    risk = out["risks"][0]
    assert risk.kind == "validation"
    assert risk.source_check_id == "quote_validator"
    # Confidence should have been downgraded to low
    updated_pd = out["documents"][0]
    assert "low" in str(updated_pd.extracted.raw["_confidence"]).lower()


# ---------------------------------------------------------------------------
# RAG index subgraph (HybridStore)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rag_index_subgraph_indexes_chunks(tmp_path):
    """The rag_index_subgraph adds chunks to the HybridStore."""
    from store import HybridStore
    from subgraphs.rag_index_subgraph import build_rag_index_subgraph

    store = HybridStore(
        chroma_path=str(tmp_path / "chroma"),
        collection_name="test_collection",
    )
    graph = build_rag_index_subgraph(store)

    ingested = IngestedDocument(
        file_name="test.pdf",
        file_type="pdf",
        pages=[],
        full_text="This is the content of an English business document. It contains valuable information.",
    )
    result = await graph.ainvoke({
        "ingested": ingested,
        "doc_type": "other",
    })
    assert result["chunks_indexed"] >= 1
    assert store.chunk_count >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_search_finds_indexed_chunks(tmp_path):
    """HybridStore.search_hybrid finds relevant chunks."""
    from store import HybridStore

    store = HybridStore(
        chroma_path=str(tmp_path / "chroma_search"),
        collection_name="test_search",
    )
    chunks = [
        {
            "text": "The March invoice gross total is $3,000.00 — a price increase pattern.",
            "metadata": {"source": "invoice_march.pdf", "chunk_index": 0, "doc_type": "invoice"},
        },
        {
            "text": "The January contract has a $50,000 penalty for confidentiality breach.",
            "metadata": {"source": "nda_january.pdf", "chunk_index": 0, "doc_type": "contract"},
        },
    ]
    await store.add_chunks(chunks)

    # Vector + BM25: "penalty" → contract
    hits = await store.search_hybrid("penalty amount", top_k=2)
    assert len(hits) >= 1
    assert any("penalty" in h["text"].lower() for h in hits)
