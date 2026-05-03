"""5 chat tool -- LangChain @tool dekorátorral, build_tools(context) factory-vel.

A tool-ok egy ChatToolContext-en keresztül érik el a HybridStore-t és a
ProcessedDocument snapshot-ot. A `bind_tools()` ezeket a chat agent-hez köti.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from tools.compare_documents import build_compare_documents_tool
from tools.context import ChatToolContext
from tools.get_extraction import build_get_extraction_tool
from tools.list_documents import build_list_documents_tool
from tools.search_documents import build_search_documents_tool
from tools.validate_document import build_validate_document_tool


def build_tools(context: ChatToolContext) -> list[BaseTool]:
    """A chat 5 tool-ját építi a context-re.

    Sorrend kötött (a dummy provider router ezt feltételezi a stratégia-választásnál).
    """
    return [
        build_list_documents_tool(context),
        build_get_extraction_tool(context),
        build_search_documents_tool(context),
        build_compare_documents_tool(context),
        build_validate_document_tool(context),
    ]


__all__ = ["ChatToolContext", "build_tools"]
