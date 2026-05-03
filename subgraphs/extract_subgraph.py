"""extract_subgraph — strukturált adatkinyerés egy doksiból.

A `prototype-agentic` extract.py minta egyszerűsített LangGraph megfelelője.

Topológia:

    START
      → extract_node               (regex/LLM extract → flatten_universal)
      → END

A quote_validator_node külön a parent pipeline_graph-ban fut, a Send fan-in
UTÁN, hogy az összes doksi extracted-jét együtt látjuk és risk-eket tudjunk
generálni.

A vision/chunked/single_call routing-ot a Fázis 5-ben bővítjük (ott jön a Claude
`with_structured_output` integráció). A Fázis 3-as dummy-extractor ezeket
egyetlen szinkron path-on csinálja.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from graph.states.pipeline_state import (
    Classification,
    ExtractedData,
    IngestedDocument,
)
from nodes.extract.extract_node import extract_node


class ExtractState(TypedDict, total=False):
    """A extract subgraph belső state-je."""

    ingested: IngestedDocument
    classification: Classification
    extracted: ExtractedData
    documents: list  # a parent reducer-be megy vissza


def build_extract_subgraph():
    """Compile-olt subgraph egyetlen doksi extract-jére."""
    graph = StateGraph(ExtractState)
    graph.add_node("extract", extract_node)
    graph.add_edge(START, "extract")
    graph.add_edge("extract", END)
    return graph.compile()
