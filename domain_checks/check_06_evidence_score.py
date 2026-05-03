"""06: ISA 500 evidence hierarchy — info-only helper, NOT a Risk producer.

This module exposes ``get_evidence_score(doc_type)`` for the UI label
("classified as Invoice (99%) | ISA 500: 8/10"). It does not generate Risk
objects.

``EvidenceScoreCheck`` returns an empty list and has an empty ``applies_to``
set so the registry skips it during fan-out. The score is read separately
by the UI / classify_node display.
"""

from __future__ import annotations

from graph.states.pipeline_state import Risk


_REGULATION = "ISA 500"


# Document-type reliability score (0-10 scale per ISA 500 evidence hierarchy)
_EVIDENCE_SCORES: dict[str, int] = {
    "invoice": 8,            # External, third-party-issued
    "purchase_order": 6,     # Internal but with strong controls
    "delivery_note": 6,      # Internal/external accompanying document
    "contract": 7,           # Signed, primary legal source
    "financial_report": 5,   # Internal summary
    "other": 3,              # Uncategorized
}


def get_evidence_score(doc_type: str) -> int:
    """Document-type reliability score per ISA 500 (0-10).

    Used by the UI in the classification line: "Classified as Invoice (99%) | ISA 500: 8/10".
    """
    return _EVIDENCE_SCORES.get(doc_type, 3)


class EvidenceScoreCheck:
    """Empty check — evidence score is read by the UI, not exposed as a Risk.

    ``applies_to`` is empty so the domain_dispatch skips this entry. The
    ``evidence_score_node`` (in the risk_subgraph) likewise yields nothing,
    keeping this class formally in the registry without producing risks.
    """
    check_id = "check_06_evidence_score"
    regulation = _REGULATION
    is_hu_specific = False
    applies_to: set[str] = set()  # empty → skipped by the registry

    def apply(self, extracted: dict, doc_type: str = "other") -> list[Risk]:
        # The evidence score is rendered by the UI only, not as a Risk.
        return []
