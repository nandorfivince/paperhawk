"""12: Duplicate invoice detection (ISA 240) — package-level, invoice.

  1. Exact: same invoice number + supplier → HIGH
  2. Near match: same supplier + amount, different invoice number
     - date filter: > 13-day spread → likely monthly recurring → skip

This is NOT a per-document check; it runs at the package level. The registry
skips it during fan-out and the ``duplicate_detector_node`` (in the
risk_subgraph) calls it via a separate entry point.
"""

from __future__ import annotations

from datetime import datetime

from domain_checks.base import make_risk
from graph.states.pipeline_state import Risk
from utils.numbers import coerce_number


_REGULATION = "ISA 240 (duplicate invoice)"


def check_duplicate_invoices(documents: list[dict]) -> list[Risk]:
    """Package-level duplicate-invoice detection.

    Args:
        documents: list of {"file_name": str, "extracted": dict, "doc_type": str}

    Returns:
        Risk list — exact + near duplicates.
    """
    risks: list[Risk] = []

    # Only consider invoices
    invoices = [d for d in documents if d.get("doc_type") == "invoice"]
    if len(invoices) < 2:
        return risks

    # Build the invoice comparison records
    invoice_data: list[dict] = []
    for inv in invoices:
        ext = inv.get("extracted", {})
        issuer = (ext.get("issuer") or {})
        if isinstance(issuer, dict):
            issuer_name = issuer.get("name", "")
        else:
            issuer_name = ""
        invoice_number = ext.get("invoice_number", "") or ""
        gross = coerce_number(ext.get("total_gross"))
        date = ext.get("issue_date", "") or ""
        invoice_data.append({
            "file": inv.get("file_name", ""),
            "issuer": (issuer_name or "").strip().lower(),
            "invoice_number": str(invoice_number).strip().lower(),
            "gross": gross,
            "date": date,
        })

    # 1. Exact duplicate: same invoice_number + issuer
    for i in range(len(invoice_data)):
        for j in range(i + 1, len(invoice_data)):
            a, b = invoice_data[i], invoice_data[j]
            if (a["invoice_number"] and a["invoice_number"] == b["invoice_number"]
                    and a["issuer"] == b["issuer"]):
                risks.append(make_risk(
                    description=(
                        f"Duplicate invoice number: {a['invoice_number']} "
                        f"({a['file']} vs {b['file']})"
                    ),
                    severity="high",
                    rationale=(
                        f"Same invoice number ({a['invoice_number']}) and issuer "
                        f"({a['issuer']}) appear in two different files. "
                        f"This may indicate duplicate processing or fraud."
                    ),
                    regulation=_REGULATION,
                    source_check_id="check_12_duplicate_invoice",
                ))

    # 2. Near duplicate: same issuer + amount, different invoice number
    #    BUT: if dates are > 13 days apart, likely monthly recurring → skip
    for i in range(len(invoice_data)):
        for j in range(i + 1, len(invoice_data)):
            a, b = invoice_data[i], invoice_data[j]
            if (a["issuer"] and a["issuer"] == b["issuer"]
                    and a["gross"] is not None and b["gross"] is not None
                    and a["gross"] == b["gross"]
                    and a["invoice_number"] != b["invoice_number"]):
                # Date-based filter: exclude monthly recurring
                skip = False
                if a["date"] and b["date"]:
                    try:
                        da = datetime.strptime(a["date"][:10], "%Y-%m-%d")
                        db = datetime.strptime(b["date"][:10], "%Y-%m-%d")
                        if abs((da - db).days) > 13:
                            skip = True  # likely monthly recurring
                    except (ValueError, TypeError):
                        pass
                if not skip:
                    risks.append(make_risk(
                        description=(
                            f"Same issuer and amount, different invoice number: "
                            f"{a['file']} vs {b['file']}"
                        ),
                        severity="medium",
                        rationale=(
                            f"Issuer: {a['issuer']}, amount: {a['gross']:,.0f}, "
                            f"but different invoice numbers ({a['invoice_number']} vs "
                            f"{b['invoice_number']}). To verify: risk of duplicate "
                            f"payment."
                        ),
                        regulation=_REGULATION,
                        source_check_id="check_12_duplicate_invoice",
                    ))

    return risks


# Wrapper class for API consistency (listed in CHECK_REGISTRY but skipped during fan-out)
class DuplicateInvoiceCheck:
    check_id = "check_12_duplicate_invoice"
    regulation = _REGULATION
    is_hu_specific = False
    applies_to: set[str] = set()  # empty → registry skip; separate entry point

    def apply(self, extracted: dict) -> list[Risk]:
        # Per-doc not meaningful; only at package level via check_duplicate_invoices
        return []
