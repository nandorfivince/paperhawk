"""DocState — Send API payload for processing a single document.

The ``dispatch_ingest`` function in pipeline_graph fans out over
``state["files"]``, sending a ``Send("ingest_doc", DocState(...))`` for each
file.

DocState is minimal — only what the per-doc subgraphs need. At the end, the
``_collect_doc`` node converts it back to a ProcessedDocument and merges it
into the parent state via the ``merge_doc_results`` reducer.

Inter-subgraph data flow:
  ingest_subgraph   → doc.ingested filled
  classify_node     → doc.classification filled
  extract_subgraph  → doc.extracted filled
  rag_index_subgr.  → doc.rag_chunks_indexed incremented
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from graph.states.pipeline_state import (
    Classification,
    ExtractedData,
    IngestedDocument,
)


class DocState(TypedDict, total=False):
    """Per-document transient state under the Send API fan-out."""

    # Input (set by dispatch_ingest)
    file_name: str
    file_bytes: bytes
    started_at: datetime

    # Per-subgraph intermediate results (subgraph fills, parent collects)
    ingested: IngestedDocument | None
    classification: Classification | None
    extracted: ExtractedData | None
    rag_chunks_indexed: int

    # Errors (downstream nodes see this and either skip or convert to risk)
    error: str | None
