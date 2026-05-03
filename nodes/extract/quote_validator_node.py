"""quote_validator_node — anti-hallucination layer #7.

Validates the LLM-provided ``_quotes`` field against the source ``full_text``.
If a quote does not appear in the source (after normalization: whitespace +
diacritics + case folding), the LLM hallucinated → confidence is downgraded
to "low" and a risk is logged.

Original prototype-agentic system did not have this check; we add it here
as an explicit node.
"""

from __future__ import annotations

from graph.states.pipeline_state import ProcessedDocument, Risk
from validation.quote_validator import downgrade_confidence, validate_quotes


async def quote_validator_node(state: dict) -> dict:
    """Walk the documents list and validate each doc's _quotes field.

    Returns ``{"documents": [pd_updated], "risks": [risk_for_invalid]}``.
    The merge_doc_results and merge_risks reducers upsert into the parent state.

    NB: this node runs in the parent pipeline_graph, NOT inside extract_subgraph
    (after the Send fan-in, so we see all docs' extracted data together).
    """
    documents: list[ProcessedDocument] = state.get("documents") or []
    if not documents:
        return {}

    updated_docs: list[ProcessedDocument] = []
    new_risks: list[Risk] = []

    for pd in documents:
        if pd.extracted is None or pd.ingested is None:
            updated_docs.append(pd)
            continue

        full_text = pd.ingested.full_text or ""
        valid, invalid = validate_quotes(pd.extracted.raw, full_text)

        if invalid:
            # Downgrade confidence on invalid quotes
            new_raw = downgrade_confidence(dict(pd.extracted.raw), invalid)
            new_extracted = pd.extracted.model_copy(update={
                "raw": new_raw,
                "confidence": new_raw.get("_confidence", {}),
            })
            updated_docs.append(pd.model_copy(update={"extracted": new_extracted}))

            # Only emit a "low" severity flag if the proportion of invalid quotes
            # is significant (>= 50%). Stochastic LLM paraphrasing alone does
            # not warrant a flag.
            valid, _ = validate_quotes(pd.extracted.raw, full_text)
            total = len(invalid) + len(valid)
            invalid_ratio = len(invalid) / max(1, total)
            if invalid_ratio >= 0.5:
                new_risks.append(Risk(
                    description=(
                        f"{pd.ingested.file_name}: {len(invalid)}/{total} quote(s) not found "
                        "in the source document (suspected LLM hallucination)."
                    ),
                    severity="low",
                    rationale=(
                        "The schema-level ``_quotes`` field contains text that does not appear "
                        "in the normalized full_text. Affected fields' confidence has been "
                        "downgraded to 'low'."
                    ),
                    kind="validation",
                    affected_document=pd.ingested.file_name,
                    source_check_id="quote_validator",
                ))
        else:
            updated_docs.append(pd)

    out: dict = {}
    if updated_docs:
        out["documents"] = updated_docs
    if new_risks:
        out["risks"] = new_risks
    return out
