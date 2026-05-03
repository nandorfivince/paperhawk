"""PipelineState — global state of the main pipeline graph.

LangGraph TypedDict (because of the reducers), Pydantic v2 models in the fields
(runtime field validation). Every Send API fan-out / fan-in is collapsed via
the ``merge_doc_results`` and ``merge_risks`` reducers.

Pydantic models with ``dict`` fields (e.g. ``ExtractedData.raw``) are NOT
schema-validated — the JSON-schema-level validation is provided by
``validation/quote_validator.py`` and the runtime checks in
``schemas/pydantic_models.py``.
"""

from __future__ import annotations

from datetime import datetime
from operator import add
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pydantic models (used inside the TypedDict fields)
# ---------------------------------------------------------------------------


class PageContent(BaseModel):
    """Content of a single page (PDF/DOCX/PNG ingest output)."""

    page_number: int = 1
    text: str = ""
    is_scanned: bool = False
    """In the PDF loader's three-tier fallback: if PyMuPDF native text < 50 chars,
    is_scanned=True and we fall through to Tesseract OCR / LLM vision."""

    image_bytes: bytes | None = None
    """Set only if ``is_scanned=True`` and we go down the vision-first path
    in extract (or if the input is a .png/.jpg — vision-first by default).
    Raw image bytes."""


class IngestedDocument(BaseModel):
    """Output of the ingest_subgraph for a single document."""

    file_name: str
    file_type: str  # pdf | docx | png | jpg | txt
    pages: list[PageContent] = Field(default_factory=list)
    full_text: str = ""
    """Concatenation of all page texts with \\n\\n separator. Fed into the
    chunker for RAG."""

    tables_markdown: str = ""
    """Tables extracted by pdfplumber, formatted as Markdown."""

    table_count: int = 0
    is_scanned: bool = False
    """True if at least one page is scanned and structured data can only be
    extracted via the vision path."""


class Classification(BaseModel):
    """Output of the classify_node."""

    doc_type: str
    """invoice | delivery_note | purchase_order | contract | financial_report | other"""

    doc_type_display: str
    """Display label for the UI: 'Invoice', 'Contract', etc."""

    confidence: float = Field(ge=0.0, le=1.0)
    language: str = "en"  # en | hu | de | fr | ...
    used_vision: bool = False
    """True if classification was done via the vision-structured path (scanned doc)."""


class ExtractedData(BaseModel):
    """Output of the extract_subgraph for a single document.

    The ``raw`` dict contains the JSON-schema payload (e.g. invoice.json fields).
    The ``_quotes``, ``_confidence``, ``_source`` aliased fields are kept
    SEPARATELY because they are anti-hallucination layers: domain checks read
    ``raw`` (typed names), but chat tools return the full ExtractedData JSON.
    """

    raw: dict = Field(default_factory=dict)
    quotes: list[str] = Field(default_factory=list, alias="_quotes")
    confidence: dict = Field(default_factory=dict, alias="_confidence")
    source: dict = Field(default_factory=dict, alias="_source")

    model_config = {"populate_by_name": True}


class Risk(BaseModel):
    """A single risk / finding — every risk source uses this unified format."""

    description: str
    severity: str  # high | medium | low | info
    rationale: str = ""
    kind: str  # validation | domain_rule | plausibility | llm_analysis | cross_check
    regulation: str | None = None
    affected_document: str | None = None
    source_check_id: str | None = None
    """For domain-check risks: which check generated this (debug + filtering)."""


class ProcessedDocument(BaseModel):
    """End-to-end result for a single document: ingest + classify + extract + risks."""

    ingested: IngestedDocument
    classification: Classification | None = None
    extracted: ExtractedData | None = None
    risks: list[Risk] = Field(default_factory=list)
    """Document-level risks (NOT routed into the global state['risks'] —
    that one is centrally aggregated)."""

    rag_chunks_indexed: int = 0
    processing_seconds: float = 0.0


class ComparisonReport(BaseModel):
    """Output of three-way matching (compare_node).

    The ``matches`` items are dict-shaped MatchResult records:
    ``{status, severity, message, field_name, expected, actual, source_a, source_b}``.
    """

    invoice_filename: str | None = None
    delivery_note_filename: str | None = None
    purchase_order_filename: str | None = None
    matches: list[dict] = Field(default_factory=list)

    # Aggregated counters
    total_checks: int = 0
    ok_count: int = 0
    warning_count: int = 0
    critical_count: int = 0
    missing_count: int = 0

    overall_status: str = "ok"  # ok | warning | critical | missing
    summary: str = ""


# Forward-references for Phase 6 models
class DDPortfolioReport(BaseModel):
    """Forward stub for the Phase 6 DD assistant output."""

    contract_count: int = 0
    contracts: list[dict] = Field(default_factory=list)
    total_monthly_obligations: dict[str, float] = Field(default_factory=dict)
    expiring_soon: list[str] = Field(default_factory=list)
    high_risk_contracts: list[str] = Field(default_factory=list)
    top_red_flags: list[str] = Field(default_factory=list)
    executive_summary: str = ""
    specialist_outputs: dict = Field(default_factory=dict)


class PackageInsights(BaseModel):
    """Forward stub for the Phase 6 package insights output."""

    executive_summary: str = ""
    findings: list[dict] = Field(default_factory=list)
    key_observations: list[str] = Field(default_factory=list)
    package_type: str = "general"


# ---------------------------------------------------------------------------
# Reducers for the Send API fan-in
# ---------------------------------------------------------------------------


def merge_doc_results(
    left: list[ProcessedDocument],
    right: list[ProcessedDocument],
) -> list[ProcessedDocument]:
    """Send fan-in: FIELD-LEVEL merge keyed by file_name.

    If different per-doc Send fan-out nodes update separate fields of the same
    document (e.g. classify_per_doc → classification, rag_index_per_doc →
    rag_chunks_indexed), the reducer does NOT clobber already-set fields — it
    only refreshes not-None new values.

    The reducer is ASSOCIATIVE and PURE.
    """
    by_name: dict[str, ProcessedDocument] = {
        d.ingested.file_name: d for d in left if d.ingested
    }
    for d in right:
        if d.ingested is None:
            continue
        existing = by_name.get(d.ingested.file_name)
        if existing is None:
            by_name[d.ingested.file_name] = d
            continue
        # Field-level merge: only NOT-NONE new values overwrite
        update: dict = {}
        if d.classification is not None:
            update["classification"] = d.classification
        if d.extracted is not None:
            update["extracted"] = d.extracted
        if d.risks:
            update["risks"] = d.risks
        if d.rag_chunks_indexed:
            update["rag_chunks_indexed"] = d.rag_chunks_indexed
        if d.processing_seconds:
            update["processing_seconds"] = d.processing_seconds
        if update:
            by_name[d.ingested.file_name] = existing.model_copy(update=update)
    return list(by_name.values())


def merge_risks(left: list[Risk], right: list[Risk]) -> list[Risk]:
    """Risk dedup keyed by description (mirrors the prototype-agentic _add_risk).

    First occurrence wins (left order preserved). A risk duplicates iff the
    exact same description string appears — common because comparison risks are
    document-independent and a per-doc loop would re-add them each iteration.
    """
    seen = {r.description for r in left}
    out = list(left)
    for r in right:
        if r.description not in seen:
            out.append(r)
            seen.add(r.description)
    return out


# ---------------------------------------------------------------------------
# PipelineState TypedDict — the full graph state
# ---------------------------------------------------------------------------


class PipelineState(TypedDict, total=False):
    """The main pipeline graph state. Every node reads/updates this.

    ``total=False`` indicates that all fields are optional (not all initialized
    at START). Send API fan-out branches write back into ``documents`` and
    ``risks`` via the reducers above.
    """

    # Input
    files: list[tuple[str, bytes]]
    """[(file_name, file_bytes), ...] — fed in from the Streamlit upload."""

    # Per-doc fan-out / fan-in (with reducers)
    documents: Annotated[list[ProcessedDocument], merge_doc_results]
    risks: Annotated[list[Risk], merge_risks]

    # Aggregated outputs
    comparison: ComparisonReport | None
    report: dict
    package_insights: PackageInsights | None
    dd_report: DDPortfolioReport | None

    # Timing / progress
    started_at: datetime
    finished_at: datetime
    processing_seconds: float
    progress_events: Annotated[list[str], add]
    """Each node tick appends a string (Streamlit progress bar feed)."""
