"""DD multi-agent supervisor + Package Insights fan-out integration tests."""

from __future__ import annotations

import pytest

from graph.states.pipeline_state import (
    Classification,
    ExtractedData,
    IngestedDocument,
    PageContent,
    ProcessedDocument,
    Risk,
)


def _make_contract(
    file_name: str,
    *,
    coc: bool = False,
    non_compete: bool = False,
    auto_renew: bool = False,
    monthly_fee: float | None = None,
    total_value: float | None = None,
    expiry_date: str | None = None,
    risks: list[Risk] | None = None,
) -> ProcessedDocument:
    """Test helper for a contract ProcessedDocument."""
    raw = {
        "contract_type": "service",
        "parties": [
            {"name": "X Inc.", "role": "supplier"},
            {"name": "Y Corp.", "role": "customer"},
        ],
        "effective_date": "2026-01-01",
        "expiry_date": expiry_date,
        "total_value": total_value,
        "monthly_fee": monthly_fee,
        "monthly_fee_currency": "USD",
        "change_of_control": coc,
        "non_compete": non_compete,
        "auto_renewal": {"enabled": auto_renew},
        "_quotes": [],
        "_confidence": {},
    }
    return ProcessedDocument(
        ingested=IngestedDocument(
            file_name=file_name,
            file_type="pdf",
            pages=[PageContent(page_number=1, text=str(raw))],
            full_text=str(raw),
        ),
        classification=Classification(
            doc_type="contract",
            doc_type_display="Contract",
            confidence=0.9,
            language="en",
            used_vision=False,
        ),
        extracted=ExtractedData(raw=raw, _quotes=[], _confidence={}),
        risks=risks or [],
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dd_graph_basic_flow():
    """Two contracts → DD report built with legal + financial specialist calls."""
    from graph.dd_graph import build_dd_graph

    contracts = [
        _make_contract(
            "contract_a.pdf",
            monthly_fee=20_000,
            total_value=240_000,
            expiry_date="2027-01-01",
            coc=True,  # red flag
        ),
        _make_contract(
            "contract_b.pdf",
            monthly_fee=5_000,
            total_value=60_000,
            expiry_date="2026-08-01",  # expires within 12 months
        ),
    ]

    graph = build_dd_graph()
    state = await graph.ainvoke({"documents": contracts})

    dd_report = state.get("dd_report")
    assert dd_report is not None
    assert dd_report.contract_count == 2

    # Legal must have been called (mandatory)
    history = state.get("call_history") or []
    assert "legal" in history
    assert "financial" in history

    # Monthly obligations aggregate (USD)
    assert dd_report.total_monthly_obligations.get("USD") == 25_000

    # Top red flags include change-of-control
    assert any("change-of-control" in flag.lower() for flag in dd_report.top_red_flags)

    # Expiring soon includes contract_b
    assert "contract_b.pdf" in dd_report.expiring_soon


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dd_graph_supervisor_iteration_limit():
    """The supervisor force-ends to the synthesizer after max 4 iterations."""
    from graph.dd_graph import build_dd_graph

    contracts = [_make_contract(f"contract_{i}.pdf", monthly_fee=1_000) for i in range(5)]
    graph = build_dd_graph()
    state = await graph.ainvoke({"documents": contracts})

    iter_count = state.get("iteration_count", 0)
    assert iter_count <= 4
    assert state.get("dd_report") is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_package_insights_dummy_fallback():
    """Package insights graph with dummy LLM returns a fallback summary."""
    from graph.package_insights_graph import build_package_insights_graph

    docs = [
        _make_contract("a.pdf", risks=[
            Risk(
                description="High risk: change-of-control",
                severity="high",
                rationale="...",
                kind="domain_rule",
                source_check_id="check_09_dd_red_flags",
            ),
        ]),
        _make_contract("b.pdf"),
    ]

    # Dummy LLM (None) → graph returns the fallback message; structure is preserved.
    graph = build_package_insights_graph(llm=None)
    state = await graph.ainvoke({
        "documents": docs,
        "package_type": "dd",
    })

    insights = state.get("final_insights")
    assert insights is not None
    assert insights.package_type == "dd"
    assert insights.executive_summary  # non-empty (at least the dummy fallback)
