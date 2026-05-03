"""package_insights_graph — package-level cross-doc analysis in a single LLM call.

Simple 1-LLM-call topology:

  START
    → generate_insights (1 LLM call with ALL document data, perspective-driven
                         instructions, RISK_SYSTEM_PROMPT-style anti-hallucination)
    END → final_insights key

The ``package_type`` (audit/dd/compliance/general) selects different prompt
instructions — see ``_PACKAGE_TYPE_INSTRUCTIONS`` below.
"""

from __future__ import annotations

import json
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from graph.states.pipeline_state import PackageInsights, ProcessedDocument


class PackageInsightsState(TypedDict, total=False):
    """The package_insights_graph state."""
    documents: list[ProcessedDocument]
    package_type: str  # audit | dd | compliance | general
    final_insights: PackageInsights | None


# 4 detailed perspective instructions
_PACKAGE_TYPE_INSTRUCTIONS = {
    "audit": (
        "Analyze the document package from an audit perspective. Focus on financial "
        "anomalies: pricing patterns, signs of over-billing, quantity discrepancies, "
        "VAT anomalies, back-dating, payment-term inconsistencies. If the same "
        "service or item appears in multiple documents at different prices or "
        "quantities, that is a strong audit risk signal."
    ),
    "dd": (
        "Analyze the document package from a Due Diligence perspective in the "
        "context of a transaction. Focus on: change-of-control clauses, near-term "
        "expirations, amendments under NDA, unusually long termination notice, "
        "significant percentage price hikes, legal red-flag clauses, "
        "disproportionate penalty clauses, warranty obligations."
    ),
    "compliance": (
        "Analyze the document package from a compliance perspective. Focus on: "
        "GDPR and data-protection clauses present/absent, encryption requirements, "
        "incident-handling procedures, audit rights, liability limitations, "
        "access controls, data-processor declarations. If the contract handles "
        "PERSONAL DATA without proper data-protection language, that is a "
        "critical compliance risk."
    ),
    "general": (
        "Analyze the document package from a general business audit perspective. "
        "Focus on cross-doc patterns: consistency, missing data, anomalies, "
        "broken business logic."
    ),
}


SYSTEM_PROMPT = """You are a package-level audit assistant. You receive multiple
documents at once and look for risks and anomalies that are visible ONLY when
the documents are reviewed TOGETHER — not within a single document.

CRITICAL RULES:

1. Rely ONLY on data that actually appears in the supplied documents. NEVER
   fabricate a number, date, name, or field value.

2. If a piece of data is missing from every document, mention it as a fact
   ("missing data") — do NOT invent a value.

3. Cite specific references: which document, which field, which value you saw.
   Do not generalize.

4. Descriptions should be concise but informative: concrete numbers, dates,
   names — NOT generic "worth checking" filler.

5. Do not repeat the same observation. One risk = one entry.

6. Write in English, in a natural business tone. Avoid bureaucratic jargon:
   "comprehensive", "thorough", "in-depth", "leveraging", "implement",
   "going forward", "regulatory requirements".

7. Fill every field: executive_summary (4-6 sentences), findings (list of
   structured risks), key_observations (3-7 concise observations)."""


# Pydantic structure for ``with_structured_output()``
class _PackageFinding(BaseModel):
    description: str
    severity: str = "low"  # high | medium | low
    rationale: str = ""
    affected_documents: list[str] = Field(default_factory=list)


class _PackageInsightsResult(BaseModel):
    executive_summary: str = ""
    findings: list[_PackageFinding] = Field(default_factory=list)
    key_observations: list[str] = Field(default_factory=list)


def _build_documents_summary(documents: list[ProcessedDocument]) -> list[dict]:
    """Compact per-document representation for the LLM.

    Strips meta-fields (_quotes, _confidence, _source) to save prompt context.
    """
    summary: list[dict] = []
    for doc in documents:
        if doc.extracted is None or doc.classification is None or doc.ingested is None:
            continue
        clean_data = {
            k: v
            for k, v in (doc.extracted.raw or {}).items()
            if not k.startswith("_")
        }
        summary.append({
            "file": doc.ingested.file_name,
            "type": doc.classification.doc_type_display,
            "doc_type": doc.classification.doc_type,
            "data": clean_data,
        })
    return summary


def build_package_insights_graph(*, llm=None, checkpointer=None):
    """Compile the package_insights graph.

    Args:
        llm: optional BaseChatModel-like Runnable. If provided, one LLM call
             produces a cross-doc PackageInsights bound to the
             ``_PackageInsightsResult`` Pydantic schema. If None, dummy
             fallback (empty findings + a basic exec summary).
        checkpointer: optional checkpointer.
    """

    async def generate_insights_node(state: PackageInsightsState) -> dict:
        """Generate cross-doc analysis in a single LLM call."""
        documents = state.get("documents") or []
        package_type = state.get("package_type", "general")

        if not documents:
            return {"final_insights": PackageInsights(
                executive_summary="No processed documents are available.",
                package_type=package_type,
            )}

        # No LLM → dummy fallback
        if llm is None:
            return {"final_insights": PackageInsights(
                executive_summary=(
                    f"{len(documents)} documents in the '{package_type}' package. "
                    "Package-level AI analysis requires a configured LLM provider (vLLM/Ollama)."
                ),
                package_type=package_type,
            )}

        documents_summary = _build_documents_summary(documents)
        try:
            docs_json = json.dumps(documents_summary, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            docs_json = str(documents_summary)

        perspective = _PACKAGE_TYPE_INSTRUCTIONS.get(
            package_type, _PACKAGE_TYPE_INSTRUCTIONS["general"]
        )

        prompt = f"""{perspective}

The full data set of the document package is below (each with the extracted fields):

{docs_json}

Return a structured package-level analysis per the schema. Use concrete data
references, not generic phrasing."""

        structured_llm = llm.with_structured_output(_PackageInsightsResult)

        try:
            response: _PackageInsightsResult = await structured_llm.ainvoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
        except Exception as exc:
            return {"final_insights": PackageInsights(
                executive_summary=(
                    f"Package-level analysis failed ({type(exc).__name__}). "
                    f"Try again later or check the LLM endpoint."
                ),
                package_type=package_type,
            )}

        return {"final_insights": PackageInsights(
            executive_summary=response.executive_summary or "",
            findings=[f.model_dump() for f in response.findings],
            key_observations=list(response.key_observations or []),
            package_type=package_type,
        )}

    graph = StateGraph(PackageInsightsState)
    graph.add_node("generate_insights", generate_insights_node)
    graph.add_edge(START, "generate_insights")
    graph.add_edge("generate_insights", END)

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()
