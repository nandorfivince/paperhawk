"""classify_node — LLM-based classification for a single document.

Async node: input is a DocState-shaped dict (from the dispatch_classify Send),
output is ``{"documents": [pd_with_classification]}`` which the parent reducer
(merge_doc_results) merges into the matching ProcessedDocument.

Vision-aware: if the ingested document has ``is_scanned=True`` and
``image_bytes``, classification runs on the vision path (image-based LLM call).
Otherwise text-based.

Dummy mode: when ``settings.is_dummy`` we do NOT call the LLM — keyword
heuristics return a Classification (fast + reproducible, eval-friendly).

vLLM/Ollama mode: factory ``build_classify_node(llm)`` captures the LLM
Runnable in a closure and calls ``with_structured_output(Classification)``.
Vision-aware: for scanned docs we use the multimodal
``HumanMessage(content=[{type=image,...}, {type=text,...}])`` shape.
"""

from __future__ import annotations

import base64
import re

from langchain_core.messages import HumanMessage, SystemMessage

from config import settings
from graph.states.pipeline_state import (
    Classification,
    IngestedDocument,
    ProcessedDocument,
)


# 6 doc_type categories + display label
_DOC_TYPE_DISPLAY = {
    "invoice": "Invoice",
    "delivery_note": "Delivery Note",
    "purchase_order": "Purchase Order",
    "contract": "Contract",
    "financial_report": "Financial Report",
    "other": "Other",
}


# Keyword heuristic for dummy mode (multilingual, with word-boundary tolerance).
# Order MATTERS — delivery_note must be checked before invoice (so "delivery
# note" doesn't accidentally match the invoice keyword in some texts).
_KEYWORD_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("delivery_note", re.compile(
        r"\b(delivery\s*note|shipping\s*note|szallitolev\w*|Lieferschein)", re.I)),
    ("purchase_order", re.compile(
        r"\b(purchase\s*order|order\s*number|order\s*confirmation|"
        r"megrendel\w*|Bestellung)", re.I)),
    ("contract", re.compile(
        r"\b(contract|agreement|service\s*agreement|nda|"
        r"non[-\s]?disclosure|szerzodes|szerzodest|titoktart\w*|"
        r"kotber\w*|felmondas\w*|Vertrag)", re.I)),
    ("financial_report", re.compile(
        r"\b(income\s*statement|profit.{0,5}loss|p&l|balance\s*sheet|"
        r"cash\s*flow|financial\s*statement|"
        r"eredmenykimut\w*|merleg|penzugyi|Bilanz|Gewinn-?\s*und\s*Verlustrechnung)", re.I)),
    ("invoice", re.compile(r"\b(invoice|tax\s*invoice|szamla\w*|sz\.szam|Rechnung)", re.I)),
]


# Simplified language detection (EN/HU/DE)
_LANG_INDICATORS = {
    "en": re.compile(r"\b(the|and|or|of|is|invoice|contract|agreement)\b", re.I),
    "hu": re.compile(r"\b(es|az|hogy|nem|van|szamla|szerzodes)\b", re.I),
    "de": re.compile(r"\b(der|die|das|und|ist|rechnung|vertrag)\b", re.I),
}


def _detect_language(text: str) -> str:
    """Simple keyword-ratio language detection (default: en)."""
    if not text:
        return "en"
    snippet = text[:5000].lower()
    scores = {lang: len(pat.findall(snippet)) for lang, pat in _LANG_INDICATORS.items()}
    best = max(scores.items(), key=lambda x: x[1])
    return best[0] if best[1] >= 3 else "en"


def _classify_dummy(ingested: IngestedDocument) -> Classification:
    """Dummy classifier — keyword-based, < 1 ms."""
    text = ingested.full_text or ""
    file_name = ingested.file_name.replace("_", " ").replace("-", " ")

    # File-name-based override (often the strongest hint)
    for doc_type, pattern in _KEYWORD_RULES:
        if pattern.search(file_name):
            return Classification(
                doc_type=doc_type,
                doc_type_display=_DOC_TYPE_DISPLAY[doc_type],
                confidence=0.85,
                language=_detect_language(text),
                used_vision=ingested.is_scanned,
            )

    # Text-based
    for doc_type, pattern in _KEYWORD_RULES:
        if pattern.search(text):
            return Classification(
                doc_type=doc_type,
                doc_type_display=_DOC_TYPE_DISPLAY[doc_type],
                confidence=0.7,
                language=_detect_language(text),
                used_vision=ingested.is_scanned,
            )

    # Fallback: other
    return Classification(
        doc_type="other",
        doc_type_display=_DOC_TYPE_DISPLAY["other"],
        confidence=0.5,
        language=_detect_language(text),
        used_vision=ingested.is_scanned,
    )


# ---------------------------------------------------------------------------
# vLLM/Ollama LLM classification
# ---------------------------------------------------------------------------


_CLASSIFY_SYSTEM_PROMPT = """You are a document classifier. Categorize the uploaded document into ONE of:
invoice, delivery_note, purchase_order, contract, financial_report, other.

Work only from the document content; do not fabricate. Fill ``doc_type`` with the code
('invoice', 'delivery_note', 'purchase_order', 'contract', 'financial_report', 'other'),
and ``doc_type_display`` with the display label ('Invoice', 'Delivery Note',
'Purchase Order', 'Contract', 'Financial Report', 'Other'). ``confidence`` is a
float between 0.0 and 1.0. ``language`` is the document language ('en', 'hu', 'de'),
default 'en'. ``used_vision`` is always False (the system fills it in)."""


async def _classify_llm_text(
    structured_llm, ingested: IngestedDocument
) -> Classification:
    """Text-based LLM classification (with_structured_output)."""
    text_preview = (ingested.full_text or "")[:3000]
    user_prompt = f"Classify the following document by type:\n\n{text_preview}"
    response = await structured_llm.ainvoke([
        SystemMessage(content=_CLASSIFY_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ])
    if isinstance(response, Classification):
        response.used_vision = False
        return response
    return Classification(**response.model_dump()) if hasattr(response, "model_dump") else Classification(**dict(response))


async def _classify_llm_vision(
    structured_llm, ingested: IngestedDocument
) -> Classification:
    """Vision-based LLM classification — sends the first page image."""
    if not ingested.pages or not ingested.pages[0].image_bytes:
        # No image → fall back to text path
        return await _classify_llm_text(structured_llm, ingested)
    img_b64 = base64.standard_b64encode(ingested.pages[0].image_bytes).decode("ascii")
    msg = HumanMessage(content=[
        {"type": "text", "text": "What kind of business document is shown in this image? Classify it."},
        {
            "type": "image",
            "source_type": "base64",
            "data": img_b64,
            "mime_type": "image/png",
        },
    ])
    response = await structured_llm.ainvoke([
        SystemMessage(content=_CLASSIFY_SYSTEM_PROMPT),
        msg,
    ])
    if isinstance(response, Classification):
        response.used_vision = True
        return response
    obj = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    obj["used_vision"] = True
    return Classification(**obj)


def build_classify_node(llm=None):
    """Factory: per-doc classify node.

    Args:
        llm: A BaseChatModel-like Runnable (vLLM/Ollama/Dummy). If None or
             dummy mode, the regex-based heuristic runs.
    """
    structured_llm = None
    if llm is not None and not settings.is_dummy:
        structured_llm = llm.with_structured_output(Classification)

    async def classify_node(state: dict) -> dict:
        ingested: IngestedDocument | None = state.get("ingested")
        if ingested is None:
            return {}

        if settings.is_dummy or structured_llm is None:
            classification = _classify_dummy(ingested)
        else:
            try:
                if ingested.is_scanned:
                    classification = await _classify_llm_vision(structured_llm, ingested)
                else:
                    classification = await _classify_llm_text(structured_llm, ingested)
                # Display normalization: if the LLM returns something unknown
                if classification.doc_type not in _DOC_TYPE_DISPLAY:
                    classification.doc_type = "other"
                if classification.doc_type_display not in _DOC_TYPE_DISPLAY.values():
                    classification.doc_type_display = _DOC_TYPE_DISPLAY[classification.doc_type]
            except Exception:
                # LLM error (rate limit, network, schema fail) — fallback to dummy
                classification = _classify_dummy(ingested)

        pd = ProcessedDocument(ingested=ingested, classification=classification)
        return {"documents": [pd]}

    return classify_node


# Legacy backward-compat name (dummy mode) — works without the build factory
async def classify_node(state: dict) -> dict:
    """Legacy signature (dummy mode): equivalent to build_classify_node(None)()."""
    return await build_classify_node(None)(state)
