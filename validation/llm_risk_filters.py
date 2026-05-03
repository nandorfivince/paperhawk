"""3 anti-hallucination filters for LLM-generated risks.

1. ``filter_llm_risks(risks)`` — formal filter:
   * description ≥ 5 words
   * description contains ≥ 2 domain terms
   * description (or rationale) contains ≥ 1 concrete data point (number, date, %, filename)
   * rationale (if present) is non-empty

2. ``drop_business_normal_risks(risks, extracted)`` — semantic filter:
   6 NORMAL patterns → drop (cross-checked against extracted_data):
   * Fulfillment vs issue date ≤ 14 days
   * Payment due 0–120 days after issue
   * Standard EU VAT rate (regex matches a percentage near "VAT/MwSt/áfa")
   * Subjective "high unit price" without a concrete comparison
   * Missing PO reference on a delivery note (normal)
   * Delivery note has no amount (normal — quantity-based)

3. ``drop_repeats_of_basic(llm_risks, basic_risks)`` — word-overlap dedup:
   * if ≥ 70% of the LLM risk's content words appear in a basic risk
   * → drop (substantial repeat)
   * stopwords (HU+EN) are filtered out, 2+ char tokens are kept
"""

from __future__ import annotations

import re
from datetime import datetime


# ---------------------------------------------------------------------------
# 1. formal filter: filter_llm_risks
# ---------------------------------------------------------------------------

# Domain terms (≥ 2 must appear in the description). Multilingual (EN-first +
# HU/DE fallback for multilingual demos).
_DOMAIN_TERMS = [
    "amount", "risk", "invoice", "contract", "missing", "mismatch",
    "delivery", "order", "payment", "total", "item", "quantity",
    "date", "due", "issued", "VAT", "tax", "net", "gross", "value",
    "clause", "termination", "penalty", "liability", "expiry", "effective",
    "discrepancy", "deviation", "shortage", "overcharge",
    # Multilingual fallback
    "összeg", "eltérés", "hiány", "kockázat", "dátum", "számla", "szállít",
    "megrendel", "szerződés", "tétel", "áfa", "nettó", "bruttó",
    "határidő", "kiállít", "fizetés", "mennyiség", "klauzula",
    "felmondás", "kötbér", "felelősség", "hatály", "lejárat",
]

# Concrete-data regex patterns (≥ 1 must match)
_CONCRETE_PATTERNS = [
    re.compile(r"\d+[\s.,]?\d*"),                 # numbers (e.g. 711200, 21.3)
    re.compile(r"\d{4}-\d{2}-\d{2}"),             # ISO date YYYY-MM-DD
    re.compile(r"[A-Z]{2,}-\d+"),                 # identifier (INV-2026-001)
    re.compile(r"\w+\.\w{2,4}"),                  # filename (X.pdf)
    re.compile(r"\d+\s*%"),                       # percentage
    re.compile(r"\d+\s*(USD|EUR|HUF|GBP|CHF|Ft|\$|€|£)", re.I),  # currency amount
]


def filter_llm_risks(risks: list[dict], min_words: int = 5) -> list[dict]:
    """Formal filter: drop wishy-washy risks.

    A risk passes only if:
    1. Description has at least ``min_words`` words
    2. Description contains at least 2 domain terms
    3. Description OR rationale contains at least 1 concrete data point
    4. Rationale (if present) is non-empty
    """
    out: list[dict] = []
    for risk in risks or []:
        if not isinstance(risk, dict):
            continue
        # Accept either new EN keys or legacy HU keys (for multi-source compat)
        desc = risk.get("description") or risk.get("leiras", "") or ""
        rationale = risk.get("rationale") or risk.get("indoklas", "") or ""
        if not desc:
            continue
        if len(desc.split()) < min_words:
            continue
        desc_lower = desc.lower()
        term_count = sum(1 for term in _DOMAIN_TERMS if term.lower() in desc_lower)
        if term_count < 2:
            continue
        combined = desc + " " + rationale
        if not any(p.search(combined) for p in _CONCRETE_PATTERNS):
            continue
        if ("rationale" in risk or "indoklas" in risk) and not rationale.strip():
            continue
        out.append(risk)
    return out


# ---------------------------------------------------------------------------
# 2. semantic filter: drop_business_normal_risks
# ---------------------------------------------------------------------------

# Standard EU + global VAT rates
_STANDARD_VAT_RATES = frozenset({
    0, 5, 7, 8, 9, 10, 12, 13, 15, 17, 18, 19, 20, 21, 22, 23, 24, 25, 27,
})


def _parse_date_safe(value) -> datetime | None:
    """Safely parse a YYYY-MM-DD-prefixed string; return None on failure."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _is_business_normal_pattern(risk: dict, extracted_data: dict) -> bool:
    """Detect classic false-positive patterns by cross-checking extracted_data.

    True iff the risk describes a normal business pattern (not an anomaly).
    The orchestrator calls this after filter_llm_risks for every LLM risk.

    Deterministic: no LLM dependency, only extracted_data + words in the risk
    description. Last line of defense against false positives the model
    generates despite an explicit prompt prohibition.
    """
    if not isinstance(risk, dict):
        return False
    desc = (risk.get("description") or risk.get("leiras") or "").lower()
    if not desc:
        return False

    # ---------- Pattern 1: fulfillment vs issue date ----------
    # If the description mentions both, cross-check against extracted_data.
    # If the two dates are <= 14 days apart (any direction), that's NORMAL.
    mentions_fulfillment = (
        "fulfill" in desc or "delivery date" in desc
        or "teljesít" in desc or "teljesit" in desc
    )
    mentions_issue = (
        "issue date" in desc or "issued" in desc
        or "kiállít" in desc or "kiallit" in desc
    )
    if mentions_fulfillment and mentions_issue:
        fulfillment = _parse_date_safe(extracted_data.get("fulfillment_date"))
        issue = _parse_date_safe(extracted_data.get("issue_date"))
        if fulfillment and issue:
            diff_days = abs((issue - fulfillment).days)
            if diff_days <= 14:
                return True  # ≤ 2 weeks delta = normal billing

    # ---------- Pattern 2: payment due in normal range ----------
    # If the description mentions payment due, cross-check.
    # 0-120 days after issue = standard B2B.
    if (("payment" in desc and "due" in desc)
            or ("fizetés" in desc and "határidő" in desc)
            or ("fizetes" in desc and "hatarido" in desc)):
        issue = _parse_date_safe(extracted_data.get("issue_date"))
        due = _parse_date_safe(extracted_data.get("payment_due_date"))
        if issue and due:
            diff_days = (due - issue).days
            if 0 <= diff_days <= 120:
                return True  # 0-120 day B2B due date = normal

    # ---------- Pattern 3: standard EU VAT rate ----------
    # Match "27% VAT", "27% MwSt", "27%-os áfa-kulcs" etc.
    vat_match = re.search(
        r"(\d+)\s*%[^.,!?]{0,40}(vat|mwst|áfa|afa|kulcs|tax)",
        desc,
    )
    if vat_match:
        try:
            vat_rate = int(vat_match.group(1))
            if vat_rate in _STANDARD_VAT_RATES:
                return True
        except ValueError:
            pass

    # ---------- Pattern 4: subjective "high unit price" without comparison ----------
    # "High unit price" is only a valid risk if there's a concrete comparison
    # in package context (multi-doc, multi-month). On a single doc, a single
    # high price alone is never an anomaly.
    subjective_high_price_markers = [
        "high unit price", "unusually high price", "expensive item",
        "magas egységár", "magas egyseg ar",
        "magas ár", "magas ar",
        "szokatlanul drága", "szokatlanul draga",
    ]
    has_subjective_high = any(marker in desc for marker in subjective_high_price_markers)
    if has_subjective_high:
        # Accept only if the description includes a concrete comparison
        # (e.g. "+50%", "twice", "more than X-fold")
        has_comparison = bool(re.search(
            r"(\+\d+\s*%|–\d+\s*%|-\d+\s*%|\d+\s*-?fold|"
            r"more than|less than|twice|three times|"
            r"masfelszerese|ketszerese|haromszorosa)",
            desc,
        ))
        if not has_comparison:
            return True  # Subjective "high" without concrete comparison = skip

    # ---------- Pattern 5: missing PO reference on a delivery note ----------
    if (("purchase order" in desc or "PO reference" in desc
         or "megrendelés" in desc and "hivatkozás" in desc)
            and ("missing" in desc or "hiányz" in desc)):
        return True  # Not mandatory on a delivery note

    # ---------- Pattern 6: "delivery note has no amount" ----------
    if (("delivery note" in desc or "szállítólevél" in desc or "szallitolevel" in desc)
            and ("amount" in desc or "összeg" in desc or "osszeg" in desc)
            and ("missing" in desc or "no" in desc.split()
                 or "nem tartalmaz" in desc or "hiányz" in desc or "nincs" in desc)):
        return True  # Delivery notes are typically quantity-based

    return False


def drop_business_normal_risks(
    risks: list[dict],
    extracted: dict,
) -> list[dict]:
    """Remove normal-business patterns that are false positives.

    Final defense after filter_llm_risks (formal filter). Deterministic so the
    same input always produces the same output — important for demo stability.
    """
    if not risks:
        return []
    return [r for r in risks if not _is_business_normal_pattern(r, extracted)]


# ---------------------------------------------------------------------------
# 3. repetition detection: drop_repeats_of_basic
# ---------------------------------------------------------------------------

# Hungarian + English stopwords (short, common words that don't carry
# distinguishing meaning). Only these are filtered from the content-word set;
# no industry-specific words are excluded → the filter stays general.
_STOPWORDS = frozenset({
    # English
    "the", "an", "and", "or", "but", "if", "then", "of", "in", "on",
    "at", "to", "for", "with", "from", "by", "as", "are", "was", "were",
    "be", "been", "being", "has", "have", "had", "do", "does", "did", "this",
    "that", "these", "those", "it", "its", "which", "who", "what", "where",
    "when", "why", "how", "all", "any", "some", "no", "not", "than", "more",
    "less", "very", "much", "many", "such", "so", "also", "however",
    "is", "a",
    # Hungarian (multilingual demo)
    "az", "egy", "es", "és", "vagy", "de", "ha", "hogy", "mint", "nem",
    "csak", "meg", "már", "mar", "még", "ezt", "ezen", "azt",
    "ezzel", "azzal", "ennek", "annak", "ami", "amely", "amelyek", "amelyik",
    "amit", "amint", "ahol", "akik", "ezek", "azok", "van", "vannak", "volt",
    "voltak", "lesz", "lenni", "ne", "se", "sem", "ki", "kik", "mi",
    "mit", "mire", "miert", "miért", "lehet", "kell", "kellett",
    "kellene", "valamint", "illetve", "tehat", "tehát", "valami", "valaki",
    "azonban", "viszont", "azaz",
    "egyik", "masik", "másik", "tobb", "több", "kevesebb", "soran", "során",
    "kepest", "képest", "tekintve", "vonatkozoan", "vonatkozóan", "alapjan",
    "alapján", "szerint", "sajat", "saját",
})


def _normalize_for_compare(text: str) -> set[str]:
    """Normalize a string into a content-word set for comparison.

    Steps:
    1. Lowercase
    2. Remove punctuation + line breaks
    3. Split on whitespace
    4. Drop stopwords
    5. Drop tokens shorter than 2 characters (noise)
    """
    if not text:
        return set()
    cleaned = text.lower()
    for char in ".,;:!?\"'()[]{}/<>|":
        cleaned = cleaned.replace(char, " ")
    cleaned = " ".join(cleaned.split())
    tokens = cleaned.split()
    return {t for t in tokens if t not in _STOPWORDS and len(t) >= 2}


def _is_substantial_repeat(
    llm_risk: dict,
    basic_risks: list[dict],
    overlap_threshold: float = 0.7,
) -> bool:
    """True if the llm_risk's description has substantial overlap with a basic risk.

    The 70% threshold catches "true textual duplication" (when most words match
    verbatim), not just "talks about the same thing" comments. This is intentional:
    better to drop too few than too many.
    """
    if not isinstance(llm_risk, dict):
        return False
    llm_text = llm_risk.get("description") or llm_risk.get("leiras") or ""
    llm_words = _normalize_for_compare(llm_text)
    if not llm_words:
        return False

    for basic in basic_risks or []:
        if not isinstance(basic, dict):
            continue
        basic_text = basic.get("description") or basic.get("leiras") or ""
        basic_words = _normalize_for_compare(basic_text)
        if not basic_words:
            continue
        intersection = llm_words & basic_words
        # Compute overlap relative to the LLM risk's own length: if all
        # substantive words of the LLM risk appear in basic, it's 100% repeat.
        overlap_ratio = len(intersection) / len(llm_words)
        if overlap_ratio >= overlap_threshold:
            return True

    return False


def drop_repeats_of_basic(
    llm_risks: list[dict],
    basic_risks: list[dict],
    overlap_threshold: float = 0.7,
) -> list[dict]:
    """Remove LLM risks that are textual duplicates of basic risks.

    General word-overlap measure, with NO keyword list, NO count limit.
    Tolerance-preserving: if the LLM provides genuinely new info (e.g.
    "missing addresses", "typo in the order"), it passes through. Only
    explicit textual repeats are dropped.
    """
    if not llm_risks:
        return []
    if not basic_risks:
        return llm_risks
    return [
        r for r in llm_risks
        if not _is_substantial_repeat(r, basic_risks, overlap_threshold)
    ]
