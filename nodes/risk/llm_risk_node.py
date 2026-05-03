"""llm_risk_node — per-doc LLM contextual risk analysis.

Input (Send fan-out per-doc):
    {
        "doc_file_name": str,
        "extracted": dict,            # the doc.extracted.raw
        "basic_risks": list[Risk],    # already-found basic + domain + plausibility
    }

Output:
    {
        "llm_risks_raw": list[Risk],  # raw LLM output, NOT yet filtered
    }

The 3 anti-hallucination filters (formal → semantic → repetition dedup) run
sequentially after this in ``subgraphs/llm_risk_subgraph.py``. The risks here
are tagged ``kind="llm_analysis"``.

Architecture:
    - Built via a factory (``build_llm_risk_node(llm)``) so the LLM Runnable
      is captured in a closure
    - The LLM's ``with_structured_output(LLMRiskResult)`` API guarantees
      schema-conformance via the Pydantic model
    - If the LLM call fails (rate limit, network, dummy doesn't support), the
      node returns an empty list — basic + domain risks remain
"""

from __future__ import annotations

import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from graph.states.pipeline_state import Risk
from nodes.risk._prompts import (
    RISK_SYSTEM_PROMPT,
    RISK_USER_PROMPT_TEMPLATE,
    build_already_found_block,
)


# ---------------------------------------------------------------------------
# Pydantic schema for the LLM's structured output
# ---------------------------------------------------------------------------


class LLMRiskItem(BaseModel):
    """A single LLM-generated risk."""
    description: str
    severity: Literal["high", "medium", "low"] = "medium"
    rationale: str = ""
    affected_document: str = ""


class LLMRiskResult(BaseModel):
    """The LLM's response — Pydantic mirror of the JSON schema."""
    risks: list[LLMRiskItem] = Field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# Node factory
# ---------------------------------------------------------------------------


def build_llm_risk_node(llm):
    """Factory: capture the ``llm`` Runnable in a closure.

    ``with_structured_output(LLMRiskResult)`` returns a new Runnable that
    automatically converts the BaseChatModel's output into the Pydantic model.

    Args:
        llm: A BaseChatModel-like Runnable (vLLM/Qwen, Ollama, or Dummy).
             Must support ``with_structured_output()``.

    Returns:
        async node function that operates on the Send fan-out payload.
    """
    structured_llm = llm.with_structured_output(LLMRiskResult)

    async def llm_risk_node(state: dict) -> dict:
        extracted = state.get("extracted") or {}
        basic_risks = state.get("basic_risks") or []
        file_name = state.get("doc_file_name", "")

        if not extracted:
            return {}

        # JSON-stringify the extracted data for the LLM
        try:
            data_str = json.dumps(extracted, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            data_str = str(extracted)

        # Build the "ALREADY FOUND" block from basic_risks (dict form so the
        # LLM gets a text reference)
        basic_risks_dicts = [
            {"description": r.description if hasattr(r, "description") else r.get("description", "")}
            for r in basic_risks
        ]
        already_found = build_already_found_block(basic_risks_dicts)

        user_prompt = RISK_USER_PROMPT_TEMPLATE.format(
            data_str=data_str,
            already_found=already_found,
        )

        try:
            response: LLMRiskResult = await structured_llm.ainvoke([
                SystemMessage(content=RISK_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ])
        except Exception:
            # LLM call failed (rate limit, network, dummy doesn't know the schema) —
            # return empty so basic + domain risks remain
            return {}

        # Convert into Risk Pydantic model — ``kind="llm_analysis"`` is set
        # here so the UI can separate from rule-based findings
        out_risks: list[Risk] = []
        for item in response.risks:
            out_risks.append(Risk(
                description=item.description,
                severity=item.severity,
                rationale=item.rationale,
                kind="llm_analysis",
                affected_document=item.affected_document or file_name,
                source_check_id=None,
                regulation=None,
            ))

        # NOTE: the ``risks`` reducer (merge_risks) auto-dedups by description.
        # But the 3 filters haven't run yet — so we pass ``llm_risks_raw`` to
        # the next node (filter_llm_risks_node) which finally writes into the
        # ``risks`` reducer.
        return {
            "llm_risks_raw": out_risks,
            "doc_file_name": file_name,
            "extracted": extracted,
            "basic_risks": basic_risks,
        }

    return llm_risk_node
