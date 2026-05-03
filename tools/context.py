"""ChatToolContext -- a chat tool-ok closure-ben kapott állapot-handle-je.

A tool-ok NEM tartanak párhuzamos referenciát a feltöltött dokumentumokra —
mindig a HybridStore-ból + a "documents" listából (in-memory snapshot)
olvasnak. Ez biztosítja a friss-adat működést.

Egyszerűsített Fázis 5 design: a context-ben egy in-memory snapshot van a
ProcessedDocument-ekről + a HybridStore singleton. A Fázis 7-ben (UI) ezt
SqliteSaver-rel váltjuk fel a teljes thread_id alapú perzisztenciára.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from graph.states.pipeline_state import ProcessedDocument
from store import HybridStore


@dataclass
class ChatToolContext:
    """A chat tool-ok osztott állapot-handle-je."""

    store: HybridStore
    """A hibrid store -- a search_documents tool használja."""

    documents: dict[str, ProcessedDocument] = field(default_factory=dict)
    """file_name → ProcessedDocument map. A Streamlit UI a feltöltés után
    populates-eli a pipeline-eredményből."""

    def add_document(self, doc: ProcessedDocument) -> None:
        if doc.ingested:
            self.documents[doc.ingested.file_name] = doc

    def get_document(self, filename: str) -> ProcessedDocument | None:
        return self.documents.get(filename)

    def list_filenames(self) -> list[str]:
        return list(self.documents.keys())
