"""11: IFRS vs national-GAAP anomaly detection — B/C level, financial report.

Two classic IFRS anomalies:
  1. Goodwill amortization in an IFRS context (IAS 36: not amortizable)
  2. Operating lease in an IFRS 16 context (IFRS 16 abolished the distinction)
"""

from __future__ import annotations

from domain_checks.base import make_risk
from domain_checks.check_08_gdpr_28 import _get_full_text, _text_contains_any
from graph.states.pipeline_state import Risk


_REGULATION = "IFRS / national GAAP comparison"


_IFRS_INDICATORS = [
    "IFRS", "IAS", "International Financial Reporting",
    "fair value", "valós érték", "impairment",
]


_IFRS_ANOMALIES = [
    {
        "keywords": ["goodwill", "cégérték"],
        "conflict": ["amortization", "amortisation", "amortisationszeit",
                     "amortizáció", "értékcsökkenés"],
        "finding": "Goodwill amortization in an IFRS context",
        "explanation": (
            "Per IAS 36, goodwill is NOT amortizable; it requires only an "
            "annual impairment test. If both 'amortization' and 'IFRS' "
            "appear, this may indicate a non-conforming treatment."
        ),
    },
    {
        "keywords": ["operating lease", "operatív lízing", "operatív bérlet"],
        "conflict": ["IFRS 16", "balance sheet", "mérleg", "Bilanz"],
        "finding": "Operating lease in an IFRS 16 context",
        "explanation": (
            "Per IFRS 16, there is NO distinction between operating and "
            "finance leases on the lessee side — every lease appears on the "
            "balance sheet (right-of-use asset)."
        ),
    },
]


class IFRSHARCheck:
    check_id = "check_11_ifrs_har"
    regulation = _REGULATION
    is_hu_specific = False
    applies_to = {"financial_report"}

    def apply(self, extracted: dict) -> list[Risk]:
        risks: list[Risk] = []
        full_text = _get_full_text(extracted)

        # _get_full_text doesn't include line_items text → add financial-report-specific fields
        extra_parts: list[str] = []
        for line in (extracted.get("line_items") or []):
            if isinstance(line, dict):
                extra_parts.append(line.get("description", "") or "")
        extra_parts.append(str(extracted.get("report_type", "") or ""))
        extra_parts.append(str(extracted.get("accounting_standard", "") or ""))
        full_text = full_text + " " + " ".join(p for p in extra_parts if p)

        # First: is there an IFRS context?
        has_ifrs = _text_contains_any(full_text, _IFRS_INDICATORS)
        if not has_ifrs:
            return risks

        # Search for IFRS anomalies
        for anomaly in _IFRS_ANOMALIES:
            has_keyword = _text_contains_any(full_text, anomaly["keywords"])
            has_conflict = _text_contains_any(full_text, anomaly["conflict"])
            if has_keyword and has_conflict:
                risks.append(make_risk(
                    description=anomaly["finding"],
                    severity="medium",
                    rationale=anomaly["explanation"],
                    regulation=_REGULATION,
                    source_check_id=self.check_id,
                ))

        return risks
