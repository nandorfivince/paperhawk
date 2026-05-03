"""Unit tests for the 3 filters in ``validation/llm_risk_filters.py``.

Codifies the 6 ``_is_business_normal_pattern`` cross-checks + the formal filter
+ the word-overlap dedup logic with positive (NORMAL → SKIP) and negative
(NOT-NORMAL → KEEP) cases.
"""

from __future__ import annotations

import pytest

from validation.llm_risk_filters import (
    _is_business_normal_pattern,
    drop_business_normal_risks,
    drop_repeats_of_basic,
    filter_llm_risks,
)


# ---------------------------------------------------------------------------
# Pattern 1: fulfillment vs issue date ≤ 14 days → SKIP
# ---------------------------------------------------------------------------


def test_pattern1_fulfillment_issue_1_day_normal() -> None:
    """1-day delta → NORMAL → SKIP."""
    risk = {
        "description": "Fulfillment 2026-03-07 precedes issue date 2026-03-08 (1 day diff)",
    }
    extracted = {"fulfillment_date": "2026-03-07", "issue_date": "2026-03-08"}
    assert _is_business_normal_pattern(risk, extracted) is True


def test_pattern1_fulfillment_issue_14_days_normal() -> None:
    """14-day delta → still normal (≤14 watermark)."""
    risk = {"description": "Fulfillment 2026-03-01 precedes issue date 2026-03-15"}
    extracted = {"fulfillment_date": "2026-03-01", "issue_date": "2026-03-15"}
    assert _is_business_normal_pattern(risk, extracted) is True


def test_pattern1_fulfillment_issue_60_days_NOT_normal() -> None:
    """60+ day delta → NOT normal (>14 days, suspicious)."""
    risk = {"description": "Fulfillment 2026-01-01 precedes issue date 2026-03-15"}
    extracted = {"fulfillment_date": "2026-01-01", "issue_date": "2026-03-15"}
    assert _is_business_normal_pattern(risk, extracted) is False


# ---------------------------------------------------------------------------
# Pattern 2: payment due 0-120 days → SKIP
# ---------------------------------------------------------------------------


def test_pattern2_payment_due_30_days_normal() -> None:
    """30-day payment due → NORMAL B2B."""
    risk = {"description": "Payment due 2026-04-07 (30 days after issue)"}
    extracted = {"issue_date": "2026-03-08", "payment_due_date": "2026-04-07"}
    assert _is_business_normal_pattern(risk, extracted) is True


def test_pattern2_payment_due_120_days_normal() -> None:
    """~120-day payment due → still normal."""
    risk = {"description": "Payment due 2026-07-08 (122 days after issue)"}
    extracted = {"issue_date": "2026-03-08", "payment_due_date": "2026-07-06"}
    assert _is_business_normal_pattern(risk, extracted) is True


def test_pattern2_payment_due_backwards_NOT_normal() -> None:
    """Payment due BEFORE issue → NOT normal (reversed logic)."""
    risk = {"description": "Payment due 2026-03-01, issue date 2026-03-08"}
    extracted = {"issue_date": "2026-03-08", "payment_due_date": "2026-03-01"}
    # -7 days → outside 0-120 → keep as a risk
    assert _is_business_normal_pattern(risk, extracted) is False


# ---------------------------------------------------------------------------
# Pattern 3: standard EU VAT rate → SKIP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pct", [5, 7, 10, 18, 19, 20, 21, 22, 23, 24, 25, 27])
def test_pattern3_standard_vat_rate_normal(pct: int) -> None:
    """Standard EU VAT rates are all NORMAL.

    The regex format matches '<number>% <vat-noun>'; we use that exact form.
    """
    risk = {"description": f"{pct}% VAT rate is unusual"}
    assert _is_business_normal_pattern(risk, {}) is True


@pytest.mark.parametrize("pct", [33, 99, 150])
def test_pattern3_NON_standard_vat_NOT_normal(pct: int) -> None:
    """Non-standard VAT rates → NOT NORMAL (legitimate risk)."""
    risk = {"description": f"Unusually high {pct}% VAT applied"}
    assert _is_business_normal_pattern(risk, {}) is False


# ---------------------------------------------------------------------------
# Pattern 4: subjective high price without comparison → SKIP
# ---------------------------------------------------------------------------


def test_pattern4_high_unit_price_no_comparison_skip() -> None:
    """'High unit price' without a concrete comparison → SKIP (subjective)."""
    risk = {"description": "High unit price detected on the invoice"}
    assert _is_business_normal_pattern(risk, {}) is True


def test_pattern4_high_unit_price_with_concrete_comparison_keep() -> None:
    """'High unit price' WITH a concrete comparison → KEEP."""
    risk = {"description": "High unit price: 50% more than other invoices in the package"}
    assert _is_business_normal_pattern(risk, {}) is False


# ---------------------------------------------------------------------------
# Pattern 5: missing PO reference on a delivery note → SKIP
# ---------------------------------------------------------------------------


def test_pattern5_missing_po_reference_normal() -> None:
    """Missing PO reference on the delivery note → NORMAL."""
    risk = {"description": "Missing purchase order reference on the delivery note"}
    assert _is_business_normal_pattern(risk, {}) is True


# ---------------------------------------------------------------------------
# Pattern 6: delivery note without amount → SKIP
# ---------------------------------------------------------------------------


def test_pattern6_delivery_note_no_amount_normal() -> None:
    """Delivery note without amount → NORMAL (quantity-based)."""
    risk = {"description": "Delivery note has no amount field"}
    assert _is_business_normal_pattern(risk, {}) is True


# ---------------------------------------------------------------------------
# filter_llm_risks formal checks
# ---------------------------------------------------------------------------


def test_filter_drops_too_short() -> None:
    """< 5 words → drop."""
    risks = [{"description": "short", "rationale": "x"}]
    assert filter_llm_risks(risks) == []


def test_filter_drops_too_few_domain_terms() -> None:
    """< 2 domain terms → drop."""
    risks = [{"description": "this is a long sentence without business terms here"}]
    assert filter_llm_risks(risks) == []


def test_filter_drops_no_concrete_data() -> None:
    """No concrete data point (number, date, %, filename) → drop."""
    risks = [{"description": "invoice contract risk amount missing total"}]
    assert filter_llm_risks(risks) == []


def test_filter_keeps_valid() -> None:
    """≥ 5 words + ≥ 2 domain terms + ≥ 1 concrete fact → keep."""
    risks = [{
        "description": "Invoice 2026-03-15 has a $10,000 mismatch between net and gross",
        "rationale": "net + VAT does not equal gross",
    }]
    assert len(filter_llm_risks(risks)) == 1


# ---------------------------------------------------------------------------
# drop_repeats_of_basic
# ---------------------------------------------------------------------------


def test_drop_repeats_substantial_overlap_dropped() -> None:
    """Substantial textual overlap → drop the LLM duplicate."""
    basic = [{"description": "Math error: net 100 plus VAT 20 not equal gross 999"}]
    llm = [{"description": "Math error net 100 plus VAT 20 not equal gross 999"}]
    assert drop_repeats_of_basic(llm, basic) == []


def test_drop_repeats_genuinely_new_kept() -> None:
    """Genuinely new content → kept."""
    basic = [{"description": "Math error: net 100 plus VAT 20 not equal gross 999"}]
    llm = [{"description": "Issuer postal address missing from the invoice header"}]
    assert len(drop_repeats_of_basic(llm, basic)) == 1


# ---------------------------------------------------------------------------
# drop_business_normal_risks integration
# ---------------------------------------------------------------------------


def test_drop_business_normal_full_pipeline() -> None:
    """Mix of normal + non-normal → only non-normal pass."""
    risks = [
        {"description": "Fulfillment 2026-03-07 precedes issue date 2026-03-08 (1 day)"},
        {"description": "Math error: net + VAT does not equal gross by $10,000"},
        {"description": "20% VAT rate is unusual"},
        {"description": "Issuer tax ID missing from invoice"},
    ]
    extracted = {"fulfillment_date": "2026-03-07", "issue_date": "2026-03-08"}
    out = drop_business_normal_risks(risks, extracted)
    # 2 normal + 2 non-normal → only 2 kept
    assert len(out) == 2
    descriptions = [r["description"] for r in out]
    assert any("Math error" in d for d in descriptions)
    assert any("Issuer tax ID" in d for d in descriptions)
