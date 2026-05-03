"""get_extraction tool — fetch a single document's extracted structured data."""

from __future__ import annotations

import json

from langchain_core.tools import tool

from tools.context import ChatToolContext


def build_get_extraction_tool(ctx: ChatToolContext):
    @tool
    def get_extraction(filename: str) -> str:
        """Fetch the structured extraction for a document by filename.

        For an invoice: line items, amounts, dates.
        For a contract: clauses, terms, validity dates.

        Args:
            filename: the document filename (e.g. 'invoice_001.pdf')
        """
        pd = ctx.get_document(filename)
        if pd is None:
            available = ctx.list_filenames()
            return (
                f"Document not found: '{filename}'. "
                f"Available files: {available if available else 'no documents uploaded'}"
            )

        if pd.extracted is None:
            return f"'{filename}' has not been extracted yet (extracted=null)."

        # Return the full ExtractedData as JSON (quotes + confidence included)
        out = {
            "file": filename,
            "doc_type": pd.classification.doc_type if pd.classification else "other",
            "data": pd.extracted.raw,
            "_quotes": pd.extracted.quotes,
            "_confidence": pd.extracted.confidence,
        }
        return json.dumps(out, ensure_ascii=False, indent=2, default=str)

    return get_extraction
