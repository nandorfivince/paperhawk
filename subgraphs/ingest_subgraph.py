"""ingest_subgraph — a per-doc ingest egy compile-olt subgraph-ban.

A pipeline_graph `dispatch_ingest` a Send API-val fan-out-olja a fájlokat,
mindegyik egy DocState-tel megy be ide. A subgraph kimenete:
  * doc.ingested kitöltve egy IngestedDocument-tel
  * doc.error mezőbe kerül a hiba ha a betöltés elesik
  * vissza a parent state-be a `documents` reducer-én át

Topológia:

  format_router (suffix-alapú: pdf/docx/image/txt)
    ├→ pdf_loader_node    (PyMuPDF + Tesseract + vision-fallback)
    ├→ docx_loader_node
    ├→ image_loader_node  (vision-first)
    └→ txt_loader_node
        ↓
    ingested_collector    (DocState → ProcessedDocument shell)
        ↓
        END

Async-first: minden node `async def`. A blocking PyMuPDF/python-docx/Pillow
hívásokat `asyncio.to_thread()` wrapper-rel csomagoljuk, hogy a párhuzamos
fan-out tényleg gyorsuljon.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from graph.states.doc_state import DocState
from graph.states.pipeline_state import ProcessedDocument
from ingest.docx_loader import load_docx
from ingest.image_loader import load_image
from ingest.pdf_loader import load_pdf
from ingest.txt_loader import load_txt


# ---------------------------------------------------------------------------
# Format router — döntés melyik loader fut le
# ---------------------------------------------------------------------------


def _format_route(state: DocState) -> str:
    """A file_name suffix alapján melyik loader node-ra megy."""
    name = state.get("file_name", "").lower()
    suffix = Path(name).suffix.lstrip(".")
    if suffix == "pdf":
        return "pdf_loader"
    if suffix == "docx":
        return "docx_loader"
    if suffix in {"png", "jpg", "jpeg"}:
        return "image_loader"
    if suffix == "txt":
        return "txt_loader"
    # Ismeretlen: txt-ként próbáljuk (best-effort)
    return "txt_loader"


# ---------------------------------------------------------------------------
# Loader node-ok (async wrapper a blocking lib-eken)
# ---------------------------------------------------------------------------


async def pdf_loader_node(state: DocState) -> dict:
    """PDF betöltése — 3-szintű fallback (PyMuPDF + Tesseract + vision)."""
    try:
        ingested = await asyncio.to_thread(
            load_pdf, state["file_name"], state["file_bytes"]
        )
        return {"ingested": ingested, "error": None}
    except Exception as e:
        return {"ingested": None, "error": f"PDF betöltés hiba: {e}"}


async def docx_loader_node(state: DocState) -> dict:
    try:
        ingested = await asyncio.to_thread(
            load_docx, state["file_name"], state["file_bytes"]
        )
        return {"ingested": ingested, "error": None}
    except Exception as e:
        return {"ingested": None, "error": f"DOCX betöltés hiba: {e}"}


async def image_loader_node(state: DocState) -> dict:
    """PNG/JPG -- vision-first, async wrapper."""
    try:
        suffix = Path(state["file_name"]).suffix.lstrip(".").lower() or "png"
        ingested = await asyncio.to_thread(
            load_image, state["file_name"], state["file_bytes"], suffix
        )
        return {"ingested": ingested, "error": None}
    except Exception as e:
        return {"ingested": None, "error": f"Kép betöltés hiba: {e}"}


async def txt_loader_node(state: DocState) -> dict:
    try:
        ingested = await asyncio.to_thread(
            load_txt, state["file_name"], state["file_bytes"]
        )
        return {"ingested": ingested, "error": None}
    except Exception as e:
        return {"ingested": None, "error": f"TXT betöltés hiba: {e}"}


async def ingested_collector_node(state: DocState) -> dict:
    """A subgraph utolsó node-ja — egységesíti a kimenetet a parent state-be.

    Ha a betöltés sikeres, kész a `ProcessedDocument(ingested=...)`. Ha nem,
    a downstream classify/extract subgraph-ok a `state["error"]` mezőre
    figyelnek és skip-elik a doksit.
    """
    # Itt nem kell semmit csinálni -- a parent reducer a következő lépésnél
    # (classify_node) a documents listába rakja a ProcessedDocument-et.
    # Ez a node helyfoglaló a tracing-hez (egy fix vég-pont a subgraph-ban).
    return {}


# ---------------------------------------------------------------------------
# Subgraph builder
# ---------------------------------------------------------------------------


def build_ingest_subgraph():
    """Compile-olt subgraph egyetlen doksi ingest-jére.

    Bemenet: DocState (file_name + file_bytes + started_at).
    Kimenet: DocState (ingested kitöltve, vagy error).

    A subgraph önállóan invoke-olható (`compiled.invoke({...})`) — ez segít
    az integration teszteknél.
    """
    graph = StateGraph(DocState)

    graph.add_node("pdf_loader", pdf_loader_node)
    graph.add_node("docx_loader", docx_loader_node)
    graph.add_node("image_loader", image_loader_node)
    graph.add_node("txt_loader", txt_loader_node)
    graph.add_node("ingested_collector", ingested_collector_node)

    # Conditional edge a START-tól -- a suffix alapján melyik loader fut
    graph.add_conditional_edges(
        START,
        _format_route,
        {
            "pdf_loader": "pdf_loader",
            "docx_loader": "docx_loader",
            "image_loader": "image_loader",
            "txt_loader": "txt_loader",
        },
    )

    # Mindegyik loader → ingested_collector → END
    for loader in ("pdf_loader", "docx_loader", "image_loader", "txt_loader"):
        graph.add_edge(loader, "ingested_collector")
    graph.add_edge("ingested_collector", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Pipeline-szintű convenience wrapper a per-doc subgraph hívására
# ---------------------------------------------------------------------------


async def ingest_one_doc(file_name: str, file_bytes: bytes) -> ProcessedDocument | None:
    """Egy doksit lefuttat az ingest_subgraph-on át, ProcessedDocument shell-t ad vissza.

    Ha a betöltés elesik, None-t ad vissza (downstream skip + risk log).
    Az integration teszteknél hasznos: a teljes subgraph end-to-end tesztelhető
    LLM nélkül.
    """
    graph = build_ingest_subgraph()
    result = await graph.ainvoke({
        "file_name": file_name,
        "file_bytes": file_bytes,
        "started_at": datetime.now(),
    })
    ingested = result.get("ingested")
    if ingested is None:
        return None
    return ProcessedDocument(ingested=ingested)
