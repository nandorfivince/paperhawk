"""extract_node — structured data extraction for a single document.

Three paths:
  * Dummy mode: regex-based ``extract_dummy()`` (fast, reproducible, eval-friendly)
  * vLLM/Ollama mode: ``with_structured_output(pydantic_for(doc_type))`` —
    vision for scanned PDFs, chunking for very long native text
    (>SINGLE_CALL_THRESHOLD), single-call for average-sized docs.

The node input is a DocState (Send payload); the output is
``{"documents": [pd_with_extracted]}``.

The schemas/ + flatten_universal combination ensures that an unknown doc_type
is still flattened to typed field names that the downstream domain checks
can consume.
"""

from __future__ import annotations

import base64

from langchain_core.messages import HumanMessage, SystemMessage

from config import settings
from graph.states.pipeline_state import (
    Classification,
    ExtractedData,
    IngestedDocument,
    ProcessedDocument,
)
from nodes.extract._dummy_extractor import extract_dummy
from schemas import flatten_universal, pydantic_for
from store.chunking import chunk_text, needs_chunking


_EXTRACT_SYSTEM_PROMPT = """You are a document-processing system. Extract structured data
from the supplied document according to the JSON schema.

CRITICAL RULES (anti-hallucination):
1. Only return data that ACTUALLY appears verbatim in the document.
2. If a field cannot be found, return null — NEVER fabricate data.
3. Copy amounts EXACTLY from the document. Do NOT compute, do NOT round.
4. The ``_quotes`` field must contain VERBATIM excerpts from the document
   that justify the most important extracted values (amounts, dates, names).
   Do NOT paraphrase, do NOT compose snippets, do NOT change the order — copy
   exactly as you read it (max 200 chars per quote). When in doubt, OMIT a
   quote rather than modifying it.
5. The ``_confidence`` field marks how certain you are: "high" if it's
   clearly there, "medium" if interpretation was needed, "low" if uncertain.
6. If the document is not in English, still use the SCHEMA field names —
   translate the values' meaning, but keep the field keys exactly as in the schema.

ESPECIALLY FOR CONTRACTS:
- The ``termination_terms`` field is MANDATORY if the text contains a
  "Termination", "Felmondás", "Kündigung" section or clause — even with just
  a 30/60/90-day standard notice.
- The ``governing_law`` field is MANDATORY if the text mentions "Governing law",
  "Applicable law", "Hungarian Civil Code", "BGB", "Anwendbares Recht" — even briefly.
- The ``parties`` list must contain every party (issuer, supplier, customer,
  lessor, lessee, etc.).
- Fill ``effective_date`` and ``expiry_date`` whenever the text mentions
  "Effective date", "Vertragsbeginn", "Hatály kezdete".
- Set ``change_of_control``, ``non_compete``, ``auto_renewal`` based on the
  presence of those clauses (even by reference).
"""


def _model_to_dict(response) -> dict:
    """Pydantic v2 model → dict (by_alias=True so the ``_quotes`` aliases stay)."""
    if hasattr(response, "model_dump"):
        return response.model_dump(by_alias=True, exclude_none=False)
    return dict(response) if response else {}


def _merge_extracted(base: dict, new: dict) -> dict:
    """Merge results from multi-page / chunked extraction."""
    if not base:
        return new
    for key, value in new.items():
        if value is not None and (key not in base or base[key] is None):
            base[key] = value
        elif isinstance(value, list) and isinstance(base.get(key), list):
            base[key].extend(value)
    return base


async def _extract_llm_text_single_call(
    structured_llm, ingested: IngestedDocument, doc_type: str
) -> dict:
    """Single LLM call — native text, average-sized document."""
    sections = [
        f"Extract all data from the following {doc_type} document:",
        "",
        ingested.full_text or "",
    ]
    if ingested.tables_markdown:
        sections.extend([
            "",
            "Tables extracted with pdfplumber (Markdown form, you may also cite these in _quotes):",
            "",
            ingested.tables_markdown,
        ])
    response = await structured_llm.ainvoke([
        SystemMessage(content=_EXTRACT_SYSTEM_PROMPT),
        HumanMessage(content="\n".join(sections)),
    ])
    return _model_to_dict(response)


async def _extract_llm_chunked(
    structured_llm, ingested: IngestedDocument, doc_type: str
) -> dict:
    """Chunked LLM call — long text, per-chunk extraction + merge."""
    chunks = chunk_text(ingested.full_text or "")
    all_data: dict = {}
    for idx, chunk in enumerate(chunks, start=1):
        sections = [
            f"Extract all data from chunk {idx}/{len(chunks)} of the following {doc_type} document:",
            "",
            chunk,
        ]
        if idx == 1 and ingested.tables_markdown:
            sections.extend([
                "",
                "Tables extracted from the document (Markdown form):",
                "",
                ingested.tables_markdown,
            ])
        try:
            response = await structured_llm.ainvoke([
                SystemMessage(content=_EXTRACT_SYSTEM_PROMPT),
                HumanMessage(content="\n".join(sections)),
            ])
            chunk_data = _model_to_dict(response)
        except Exception:
            continue
        all_data = _merge_extracted(all_data, chunk_data)
    return all_data


async def _extract_llm_vision(
    structured_llm, ingested: IngestedDocument, doc_type: str
) -> dict:
    """Vision LLM call — scanned PDF: per-page extraction + merge."""
    all_data: dict = {}
    for page in ingested.pages:
        if not page.image_bytes:
            continue
        img_b64 = base64.standard_b64encode(page.image_bytes).decode("ascii")
        msg = HumanMessage(content=[
            {
                "type": "text",
                "text": f"Extract all data from this {doc_type} document.",
            },
            {
                "type": "image",
                "source_type": "base64",
                "data": img_b64,
                "mime_type": "image/png",
            },
        ])
        try:
            response = await structured_llm.ainvoke([
                SystemMessage(content=_EXTRACT_SYSTEM_PROMPT),
                msg,
            ])
            page_data = _model_to_dict(response)
        except Exception:
            continue
        all_data = _merge_extracted(all_data, page_data)
    return all_data


def build_extract_node(llm=None):
    """Factory: per-doc extract node.

    Args:
        llm: A BaseChatModel-like Runnable (vLLM/Ollama/Dummy). If None or
             dummy mode, the regex-based dummy extractor runs.

    Note: ``with_structured_output(pydantic_for(doc_type))`` is built per
    doc_type, so we cache the structured_llm per doc_type.
    """
    structured_cache: dict[str, object] = {}

    def _get_structured(doc_type: str):
        if doc_type not in structured_cache:
            structured_cache[doc_type] = llm.with_structured_output(pydantic_for(doc_type))
        return structured_cache[doc_type]

    async def extract_node(state: dict) -> dict:
        ingested: IngestedDocument | None = state.get("ingested")
        classification: Classification | None = state.get("classification")
        if ingested is None or classification is None:
            return {}

        doc_type = classification.doc_type
        file_name = ingested.file_name
        full_text = ingested.full_text or ""

        if settings.is_dummy or llm is None:
            raw = extract_dummy(full_text, doc_type, file_name)
        else:
            try:
                structured_llm = _get_structured(doc_type)
                if ingested.is_scanned:
                    raw = await _extract_llm_vision(structured_llm, ingested, doc_type)
                elif needs_chunking(full_text):
                    raw = await _extract_llm_chunked(structured_llm, ingested, doc_type)
                else:
                    raw = await _extract_llm_text_single_call(structured_llm, ingested, doc_type)

                # If LLM totally failed → dummy fallback (basic fields)
                if not raw:
                    raw = extract_dummy(full_text, doc_type, file_name)
            except Exception:
                raw = extract_dummy(full_text, doc_type, file_name)

        # Flatten the universal schema into typed fields if needed
        raw = flatten_universal(raw, doc_type=doc_type)

        # _source must be present
        if "_source" not in raw or not isinstance(raw.get("_source"), dict):
            raw["_source"] = {"file_name": file_name}
        elif not raw["_source"].get("file_name"):
            raw["_source"]["file_name"] = file_name

        extracted = ExtractedData(
            raw=raw,
            _quotes=raw.get("_quotes") or [],
            _confidence=raw.get("_confidence") or {},
            _source=raw.get("_source"),
        )

        pd = ProcessedDocument(
            ingested=ingested,
            classification=classification,
            extracted=extracted,
        )
        return {"documents": [pd]}

    return extract_node


# Legacy backward-compatible name (dummy mode)
async def extract_node(state: dict) -> dict:
    """Legacy signature (dummy mode): equivalent to build_extract_node(None)()."""
    return await build_extract_node(None)(state)
