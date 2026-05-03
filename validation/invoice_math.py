"""Invoice math validation — Python deterministic, NOT LLM-dependent.

Mirrors prototype-agentic-langgraph's validate_invoice_math:
  * line items' net total ≈ total_net (±1 tolerance)
  * total_net + total_vat ≈ total_gross (±1 tolerance)
  * per-line: net × VAT% ≈ vat amount (max(1, net × 1%))
  * per-line: net + vat ≈ gross

Every math error is severity "high" (below ±1 is considered fine; above is suspicious).
"""

from __future__ import annotations

from utils.numbers import coerce_number


def validate_invoice_math(extracted: dict) -> list[dict]:
    """Invoice arithmetic validation. Returns a list of risk dicts."""
    errors: list[dict] = []

    items = extracted.get("line_items") or []
    net_total = coerce_number(extracted.get("total_net"))
    vat_total = coerce_number(extracted.get("total_vat"))
    gross_total = coerce_number(extracted.get("total_gross"))

    # Line items' net total ≈ total_net
    if items and net_total is not None:
        calc = 0.0
        for item in items:
            if not isinstance(item, dict):
                continue
            n = coerce_number(item.get("total_net"))
            if n is not None:
                calc += n
        if calc > 0 and abs(calc - net_total) > 1:
            errors.append({
                "type": "math_error",
                "severity": "high",
                "message": (
                    f"Line items' net total ({calc:.0f}) does not match "
                    f"the document total ({net_total:.0f})"
                ),
            })

    # net_total + vat_total ≈ gross_total
    if net_total is not None and vat_total is not None and gross_total is not None:
        expected = net_total + vat_total
        if abs(expected - gross_total) > 1:
            errors.append({
                "type": "math_error",
                "severity": "high",
                "message": (
                    f"Net ({net_total:.0f}) + VAT ({vat_total:.0f}) = "
                    f"{expected:.0f}, but gross = {gross_total:.0f}"
                ),
            })

    # Per-line item math
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        item_net = coerce_number(item.get("total_net"))
        item_vat = coerce_number(item.get("total_vat"))
        item_gross = coerce_number(item.get("total_gross"))
        item_vat_rate = coerce_number(item.get("vat_rate"))
        name = item.get("description", f"item #{idx + 1}")

        # VAT calc: net × rate/100 ≈ vat amount
        if (
            item_net is not None
            and item_vat_rate is not None
            and item_vat is not None
            and item_vat_rate > 0
        ):
            expected_vat = item_net * item_vat_rate / 100
            tol = max(1.0, item_net * 0.01)
            if abs(expected_vat - item_vat) > tol:
                errors.append({
                    "type": "math_error",
                    "severity": "high",
                    "message": (
                        f"Line '{name}': net ({item_net:.0f}) × "
                        f"{item_vat_rate:.0f}% = {expected_vat:.0f}, "
                        f"but VAT = {item_vat:.0f}"
                    ),
                })

        # Gross: net + vat ≈ gross
        if (
            item_net is not None
            and item_vat is not None
            and item_gross is not None
        ):
            expected_gross = item_net + item_vat
            if abs(expected_gross - item_gross) > 1:
                errors.append({
                    "type": "math_error",
                    "severity": "high",
                    "message": (
                        f"Line '{name}': net ({item_net:.0f}) + "
                        f"VAT ({item_vat:.0f}) = {expected_gross:.0f}, "
                        f"but gross = {item_gross:.0f}"
                    ),
                })

    return errors
