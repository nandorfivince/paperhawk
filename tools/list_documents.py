"""list_documents tool -- feltöltött fájlok listázása."""

from __future__ import annotations

import json

from langchain_core.tools import tool

from tools.context import ChatToolContext


def build_list_documents_tool(ctx: ChatToolContext):
    @tool
    def list_documents() -> str:
        """Listázza a feltöltött dokumentumokat fájlnévvel és típussal.

        HASZNÁLD ELSŐKÉNT, ha nem tudod milyen dokumentumok érhetők el.
        """
        if not ctx.documents:
            return "Nincsenek feltöltött dokumentumok."

        items = []
        for fname, pd in ctx.documents.items():
            doc_type = (
                pd.classification.doc_type_display
                if pd.classification
                else "ismeretlen"
            )
            confidence = (
                f"{pd.classification.confidence:.0%}"
                if pd.classification
                else "?"
            )
            items.append({
                "fajl": fname,
                "tipus": doc_type,
                "doc_type": pd.classification.doc_type if pd.classification else "egyeb",
                "biztonsag": confidence,
            })

        return json.dumps(items, ensure_ascii=False, indent=2)

    return list_documents
