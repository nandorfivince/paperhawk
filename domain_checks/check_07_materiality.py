"""07: Materiality (ISA 320) — info level, universal.

Per-document materiality threshold based on the document's total value:
  * overall      = total * 0.0193 (1.93% — parity watermark)
  * performance  = overall * 0.73
  * trivial      = overall * 0.047

The info-level risk is rendered in blue ("low" tint) in the Report tab.
"""

from __future__ import annotations

from domain_checks.base import make_risk
from graph.states.pipeline_state import Risk
from utils.numbers import coerce_number


_REGULATION = "ISA 320"


class MaterialityCheck:
    check_id = "check_07_materiality"
    regulation = _REGULATION
    is_hu_specific = False
    applies_to = {"invoice", "contract", "financial_report"}

    def apply(self, extracted: dict) -> list[Risk]:
        # Document total value:
        # 1. total_gross (invoice)
        # 2. value.amount or total_value (contract)
        doc_value = coerce_number(extracted.get("total_gross"))
        if doc_value is None:
            value_dict = extracted.get("value") or {}
            if isinstance(value_dict, dict):
                doc_value = coerce_number(value_dict.get("amount"))
            else:
                doc_value = coerce_number(extracted.get("total_value"))

        if doc_value is None or doc_value <= 0:
            return []

        # Overall materiality: 1.93% of the document total (conservative parity watermark)
        overall = doc_value * 0.0193
        performance = overall * 0.73
        trivial = overall * 0.047

        return [make_risk(
            description=(
                f"Materiality threshold (ISA 320): {overall:,.0f} "
                f"(document total: {doc_value:,.0f}, ~2%)"
            ),
            severity="info",
            rationale=(
                f"Per ISA 320, the materiality threshold for this document is "
                f"{overall:,.0f}. Trivial: {trivial:,.0f}, "
                f"performance: {performance:,.0f}."
            ),
            regulation=_REGULATION,
            source_check_id=self.check_id,
        )]
