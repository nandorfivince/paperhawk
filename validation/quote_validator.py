"""Quote validator — anti-hallucination layer #7.

The schema-level ``_quotes`` field requires verbatim document quotes from the
LLM. This validator checks whether each quote appears in the ``full_text``
(in normalized form: whitespace + diacritics + case-folded). If a quote is
not found in the source, the LLM hallucinated → low confidence + risk log.

The original prototype-agentic system did not have this; only the LLM prompt
asked for citations. The LangGraph implementation adds an explicit verifier node.
"""

from __future__ import annotations

import re
import unicodedata


def _normalize(text: str) -> str:
    """Whitespace + diacritics + case folding.

    NFKD decomposition splits the diacritic (e.g. á → a + combining acute), then
    we drop the combining marks → "a".
    """
    if not text:
        return ""
    # Strip diacritics
    nfkd = unicodedata.normalize("NFKD", text)
    no_accent = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Collapse whitespace (multiple → single space)
    normalized = re.sub(r"\s+", " ", no_accent.lower()).strip()
    return normalized


def quote_in_source(quote: str, source_text: str, *, min_chars: int = 15) -> bool:
    """Check whether the quote (normalized) appears in the source text.

    Args:
        quote: the LLM-provided quote
        source_text: the IngestedDocument.full_text (full document text)
        min_chars: skip short quotes (< 15 chars — e.g. numeric values like
                   "1,200,000 USD" or "2026-02-28" where the LLM may apply
                   a different format although the content is correct)

    Sometimes the LLM modifies number formatting (e.g. "1240160" vs "1 240 160 HUF"),
    which fails a verbatim text match. Hence the min_chars cutoff, and the
    downstream node downgrades severity to "low" instead of "high".
    """
    q = _normalize(quote)
    s = _normalize(source_text)
    if not q or len(q) < min_chars:
        return True  # Too short → accept (avoid false positives)
    return q in s


def validate_quotes(
    extracted_raw: dict,
    full_text: str,
) -> tuple[list[str], list[str]]:
    """Verify ``extracted_raw["_quotes"]`` against ``full_text``.

    Returns:
        (valid_quotes, invalid_quotes): lists of quotes that exist in the source
        and quotes that do not. Invalid quotes are unreliable (suspected
        hallucination) → downstream confidence is set to "low" and a risk is logged.
    """
    quotes = (
        extracted_raw.get("_quotes")
        or extracted_raw.get("quotes")
        or []
    )
    if not isinstance(quotes, list):
        return [], []

    valid: list[str] = []
    invalid: list[str] = []

    for q in quotes:
        if not isinstance(q, str):
            continue
        if quote_in_source(q, full_text):
            valid.append(q)
        else:
            invalid.append(q)

    return valid, invalid


def downgrade_confidence(extracted_raw: dict, invalid_quotes: list[str]) -> dict:
    """If invalid quotes exist, downgrade ``_confidence`` fields to "low".

    Aggressive policy: if NO valid quote exists, mark every confidence as "low".
    Otherwise keep the LLM's original confidence values (>= 50% valid).
    """
    if not invalid_quotes:
        return extracted_raw

    confidence = extracted_raw.get("_confidence") or {}
    quote_count = len(extracted_raw.get("_quotes") or extracted_raw.get("quotes") or [])
    valid_count = quote_count - len(invalid_quotes)
    valid_ratio = valid_count / max(1, valid_count + len(invalid_quotes))

    # Below 50% valid → all confidence → low
    if valid_ratio < 0.5:
        confidence = {k: "low" for k in confidence} if confidence else {"_overall": "low"}
        extracted_raw["_confidence"] = confidence

    return extracted_raw
