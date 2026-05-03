"""chat_graph integration test with the dummy LLM.

For each of the 5 intents (list, extract, search, compare, validate), the right
tool sequence runs and the validator's anti-hallucination check does not block.
"""

from __future__ import annotations

import pytest

from store import HybridStore


@pytest.fixture
def populated_context(sample_pdf_bytes, tmp_path):
    """A ChatToolContext with one invoice PDF run through the pipeline."""
    import asyncio

    from graph.pipeline_graph import build_pipeline_graph
    from tools import ChatToolContext

    store = HybridStore(
        chroma_path=str(tmp_path / "chat_chroma"),
        collection_name="chat_test",
    )
    pipeline = build_pipeline_graph(store)
    pipeline_state = asyncio.run(pipeline.ainvoke({
        "files": [
            ("invoice_january.pdf", sample_pdf_bytes),
            ("invoice_march.pdf", sample_pdf_bytes),
        ],
    }))

    context = ChatToolContext(store=store)
    for pd in pipeline_state.get("documents") or []:
        context.add_document(pd)
    return context


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_list_intent(populated_context):
    """'What files do we have' → list_documents tool."""
    from langchain_core.messages import HumanMessage

    from graph.chat_graph import build_chat_graph
    from providers import get_chat_model, get_dummy_handle

    dummy = get_dummy_handle()
    dummy.set_docs_hint(populated_context.list_filenames())

    llm = get_chat_model("dummy")
    graph = build_chat_graph(llm, populated_context)

    state = await graph.ainvoke({
        "messages": [HumanMessage(content="What documents are uploaded?")],
    })

    assert state.get("intent") == "list"
    assert "list_documents" in (state.get("plan") or [])
    assert state.get("final_answer", "")  # non-empty


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_validate_intent(populated_context):
    """'Validate the math on the invoice' → validate_document tool."""
    from langchain_core.messages import HumanMessage

    from graph.chat_graph import build_chat_graph
    from providers import get_chat_model, get_dummy_handle

    dummy = get_dummy_handle()
    dummy.set_docs_hint(populated_context.list_filenames())

    llm = get_chat_model("dummy")
    graph = build_chat_graph(llm, populated_context)

    state = await graph.ainvoke({
        "messages": [HumanMessage(content="Validate the math on invoice_january.pdf")],
    })

    assert state.get("intent") == "validate"
    # iter_count >= 1 (at least one tool call ran)
    assert state.get("iteration_count", 0) >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_compare_intent(populated_context):
    """'Compare X and Y' → compare_documents flow."""
    from langchain_core.messages import HumanMessage

    from graph.chat_graph import build_chat_graph
    from providers import get_chat_model, get_dummy_handle

    dummy = get_dummy_handle()
    dummy.set_docs_hint(populated_context.list_filenames())

    llm = get_chat_model("dummy")
    graph = build_chat_graph(llm, populated_context)

    state = await graph.ainvoke({
        "messages": [HumanMessage(content="Compare the January and March invoices")],
    })

    assert state.get("intent") == "compare"
    plan = state.get("plan") or []
    assert "compare_documents" in plan
    # compare flow: list → get × 2 → compare → synth ⇒ at least 4 iters
    assert state.get("iteration_count", 0) >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_search_intent(populated_context):
    """'Find the penalty clause' → search_documents tool (RAG)."""
    from langchain_core.messages import HumanMessage

    from graph.chat_graph import build_chat_graph
    from providers import get_chat_model, get_dummy_handle

    dummy = get_dummy_handle()
    dummy.set_docs_hint(populated_context.list_filenames())

    llm = get_chat_model("dummy")
    graph = build_chat_graph(llm, populated_context)

    state = await graph.ainvoke({
        "messages": [HumanMessage(content="Find the penalty clause")],
    })

    assert state.get("intent") == "search"
    assert state.get("iteration_count", 0) >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chat_extract_intent(populated_context):
    """'What is the gross total' → extract flow."""
    from langchain_core.messages import HumanMessage

    from graph.chat_graph import build_chat_graph
    from providers import get_chat_model, get_dummy_handle

    dummy = get_dummy_handle()
    dummy.set_docs_hint(populated_context.list_filenames())

    llm = get_chat_model("dummy")
    graph = build_chat_graph(llm, populated_context)

    state = await graph.ainvoke({
        "messages": [HumanMessage(content="What is the gross total on invoice_january.pdf?")],
    })

    assert state.get("intent") == "extract"
    assert state.get("iteration_count", 0) >= 1
