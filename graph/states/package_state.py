"""PackageInsightsState — 5-perspective fan-out + synthesis."""

from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict

from graph.states.pipeline_state import (
    PackageInsights,
    ProcessedDocument,
)


class PackageInsightsState(TypedDict, total=False):
    """The package_insights_graph state."""

    documents: list[ProcessedDocument]
    package_type: str  # audit | dd | compliance | general

    # Per-perspective fan-out outputs (appended via reducer)
    perspectives: Annotated[list[dict], add]
    """[{perspective: str, summary: str, findings: list[str]}, ...]"""

    final_insights: PackageInsights | None
