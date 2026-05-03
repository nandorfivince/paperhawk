"""Streamlit UI — Agentic Document Intelligence (LangGraph).

5 tabs: Upload, Results, Chat, DD Assistant, Report.

LangGraph is async-first; the Streamlit (uvloop) compatibility is handled by
the ``app.async_runtime.AsyncRuntime`` singleton with a long-lived background
event loop. The caller invokes via the synchronous ``run_async()`` wrapper.
"""

from __future__ import annotations

# Streamlit runs app/main.py directly so the project root is added explicitly
# to sys.path; that lets ``from app.streaming`` and ``from config`` resolve.
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import json  # noqa: E402
import traceback  # noqa: E402
import uuid  # noqa: E402
from collections import defaultdict  # noqa: E402
from datetime import datetime  # noqa: E402

import streamlit as st  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402

from app.streaming import run_async, run_with_progress  # noqa: E402
from config import settings  # noqa: E402
from graph.chat_graph import build_chat_graph  # noqa: E402
from graph.dd_graph import build_dd_graph  # noqa: E402
from graph.package_insights_graph import build_package_insights_graph  # noqa: E402
from graph.pipeline_graph import build_pipeline_graph  # noqa: E402
from providers import get_chat_model, get_dummy_handle  # noqa: E402
from store import HybridStore  # noqa: E402
from tools import ChatToolContext  # noqa: E402
from utils.docx_export import build_docx_sync  # noqa: E402


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Agentic Document Intelligence — LangGraph",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------


def _init_session_state() -> None:
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = f"st_{uuid.uuid4().hex[:12]}"
    if "store" not in st.session_state:
        st.session_state.store = HybridStore()
    if "tool_context" not in st.session_state:
        st.session_state.tool_context = ChatToolContext(store=st.session_state.store)
    if "pipeline_state" not in st.session_state:
        st.session_state.pipeline_state = None
    if "dd_contracts_summary" not in st.session_state:
        st.session_state.dd_contracts_summary = []
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "docx_bytes" not in st.session_state:
        st.session_state.docx_bytes = None


_init_session_state()


# ---------------------------------------------------------------------------
# Sidebar — 3 buttons (Reset, Clear chat history, Clear vector store)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Settings")
    st.info(f"LLM Provider: **{settings.llm_profile}**")

    if st.session_state.pipeline_state:
        n_docs = len(st.session_state.pipeline_state.get("documents") or [])
        st.success(f"Documents processed: {n_docs}")
        st.metric("Indexed chunks", st.session_state.store.chunk_count)

    st.divider()

    if st.button(
        "Full reset",
        help="Clear everything: uploaded documents, vector store, chat history, results.",
    ):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    if st.button(
        "Clear chat history",
        help="Only clears the chat conversation. Documents and results are kept.",
    ):
        st.session_state.chat_history = []
        st.rerun()

    if st.button(
        "Clear vector store",
        help="Clears the search index (ChromaDB). Chat will not be able to answer "
             "until you upload documents again. Results are preserved.",
    ):
        try:
            run_async(st.session_state.store.clear())
        except Exception:
            # Fallback: new instance if clear() fails
            st.session_state.store = HybridStore()
            st.session_state.tool_context = ChatToolContext(store=st.session_state.store)
        st.session_state.chat_history = []
        st.rerun()


# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------

st.title("Agentic Document Intelligence Platform")
st.caption("Multi-document cross-analysis for audit and legal use")


# ---------------------------------------------------------------------------
# 5 Tabs
# ---------------------------------------------------------------------------

tab_upload, tab_results, tab_chat, tab_dd, tab_report = st.tabs(
    ["Upload", "Results", "Chat", "DD Assistant", "Report"]
)


# =============================================================================
# Demo package handler
# =============================================================================

DEMO_ROOT = _PROJECT_ROOT / "test_data" / "demo_packages"

DEMO_PACKAGES = [
    {
        "key": "audit_demo",
        "label": "Audit Demo",
        "package_type": "audit",
        "description": "3 invoices from the same supplier; the March one is 50% pricier.",
    },
    {
        "key": "dd_demo",
        "label": "Due Diligence Demo",
        "package_type": "dd",
        "description": "NDA + service agreement + amendment in an acquisition scenario.",
    },
    {
        "key": "compliance_demo",
        "label": "Compliance Demo",
        "package_type": "compliance",
        "description": "2 contracts; one is missing the GDPR Article 28 clause.",
    },
]


def _process_demo_package(pkg: dict) -> None:
    """Process a demo package end-to-end: pipeline + package_insights + (optional) DD."""
    pkg_dir = DEMO_ROOT / pkg["key"]
    if not pkg_dir.exists():
        # Backward-compat: fall back to old HU directory name
        legacy = _PROJECT_ROOT / "test_data" / "demo_csomagok" / pkg["key"]
        if legacy.exists():
            pkg_dir = legacy
        else:
            st.error(f"Demo package directory not found: {pkg_dir}")
            return

    pdf_files = sorted(pkg_dir.glob("*.pdf"))
    if not pdf_files:
        st.error(f"No PDFs in the {pkg['label']} package: {pkg_dir}")
        return

    demo_files = [(p.name, p.read_bytes()) for p in pdf_files]
    if settings.is_dummy:
        get_dummy_handle().set_docs_hint([fn for fn, _ in demo_files])

    try:
        # 1) Pipeline with progress bar
        pipeline = build_pipeline_graph(st.session_state.store, llm=get_chat_model())
        progress_bar = st.progress(0.0, text=f"{pkg['label']}: starting pipeline...")
        total_steps = max(len(demo_files) * 4 + 6, 12)

        def _on_pipeline_progress(step: int, total: int, label: str) -> None:
            progress_bar.progress(
                min(step / total, 1.0),
                text=f"[{step}/{total}] {label}",
            )

        state = run_with_progress(
            pipeline,
            {"files": demo_files},
            on_progress=_on_pipeline_progress,
            total_steps=total_steps,
        )
        progress_bar.progress(1.0, text="Pipeline done — running package-level analysis...")

        # 2) Package insights — opt-in, runs only on demo buttons
        pkg_graph = build_package_insights_graph(llm=get_chat_model())
        pkg_state = run_async(pkg_graph.ainvoke({
            "documents": state.get("documents") or [],
            "package_type": pkg["package_type"],
        }))
        insights = pkg_state.get("final_insights")
        if insights is not None:
            state["package_insights"] = insights

        # 3) DD report — only if the package contains contracts
        contracts = [
            d for d in (state.get("documents") or [])
            if d.classification and d.classification.doc_type == "contract"
        ]
        if contracts:
            progress_bar.progress(1.0, text="DD analysis...")
            dd_graph = build_dd_graph(llm=get_chat_model())
            dd_state = run_async(dd_graph.ainvoke({"documents": contracts}))
            state["dd_report"] = dd_state.get("dd_report")
            st.session_state.dd_contracts_summary = dd_state.get("contracts") or []

        progress_bar.progress(1.0, text="Processing complete!")

        st.session_state.pipeline_state = state
        for pd in state.get("documents") or []:
            st.session_state.tool_context.add_document(pd)

        n_docs = len(state.get("documents") or [])
        n_risks = len(state.get("risks") or [])
        elapsed = state.get("processing_seconds", 0)
        st.success(
            f"{pkg['label']} loaded: {n_docs} documents in {elapsed:.1f} sec, "
            f"{n_risks} risks identified. Open the Results / DD Assistant tab."
        )
        st.rerun()
    except Exception as exc:
        st.error(f"Error processing the demo package: {exc}")
        with st.expander("Developer details (full traceback)"):
            st.code(traceback.format_exc(), language="python")


# =============================================================================
# TAB 1: Upload
# =============================================================================

with tab_upload:
    st.subheader("Upload documents")

    if st.session_state.pipeline_state:
        n_docs = len(st.session_state.pipeline_state.get("documents") or [])
        st.info(
            f"Currently {n_docs} documents are processed. "
            "Open the Results tab, or upload more files."
        )

    uploaded = st.file_uploader(
        "Drop documents here (PDF, DOCX, image, or text)",
        type=["pdf", "docx", "png", "jpg", "jpeg", "txt"],
        accept_multiple_files=True,
    )

    if uploaded and st.button("Start processing", type="primary"):
        files = [(f.name, f.read()) for f in uploaded]

        if settings.is_dummy:
            get_dummy_handle().set_docs_hint([fn for fn, _ in files])

        try:
            graph = build_pipeline_graph(st.session_state.store, llm=get_chat_model())
            progress_bar = st.progress(0.0, text="Starting...")
            total_steps = max(len(files) * 4 + 6, 12)

            def _on_progress(step: int, total: int, label: str) -> None:
                progress_bar.progress(
                    min(step / total, 1.0),
                    text=f"[{step}/{total}] {label}",
                )

            state = run_with_progress(
                graph,
                {"files": files},
                on_progress=_on_progress,
                total_steps=total_steps,
            )
            progress_bar.progress(1.0, text="Processing complete!")

            st.session_state.pipeline_state = state
            st.session_state.dd_contracts_summary = []  # reset DD on manual flow
            for pd in state.get("documents") or []:
                st.session_state.tool_context.add_document(pd)

            n_docs = len(state.get("documents") or [])
            n_risks = len(state.get("risks") or [])
            elapsed = state.get("processing_seconds", 0)
            st.success(
                f"Processed {n_docs} documents in {elapsed:.1f} sec; "
                f"{n_risks} risks identified."
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Processing error: {exc}")
            with st.expander("Developer details (full traceback)"):
                st.code(traceback.format_exc(), language="python")

    st.divider()
    st.subheader("Quick demo")
    st.caption(
        "Pre-built scenarios for the pitch. One click loads and processes the "
        "matching documents (pipeline + package-level analysis + DD if there are contracts)."
    )

    cols = st.columns(len(DEMO_PACKAGES))
    for col, pkg in zip(cols, DEMO_PACKAGES, strict=False):
        with col:
            st.markdown(f"**{pkg['label']}**")
            st.caption(pkg["description"])
            if st.button("Run", key=f"demo_{pkg['key']}"):
                _process_demo_package(pkg)


# =============================================================================
# TAB 2: Results
# =============================================================================

with tab_results:
    state = st.session_state.pipeline_state
    if state is None:
        st.info("Upload documents on the Upload tab to see results.")
    else:
        report = state.get("report") or {}
        perf = report.get("performance") or {}

        # 4 metrics
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Processing time", f"{perf.get('processing_seconds', 0):.1f} sec")
        with c2:
            st.metric("Documents", perf.get("documents", 0))
        with c3:
            st.metric("Manual estimate", f"{perf.get('manual_estimate_minutes', 0)} min")
        with c4:
            st.metric("Speedup", f"{perf.get('speedup', 0):.1f}x")

        st.divider()
        st.subheader("Classification")
        from domain_checks import get_evidence_score
        for pd_doc in state.get("documents") or []:
            if pd_doc.ingested is None:
                continue
            cls = pd_doc.classification
            col1, col2, col3 = st.columns([3, 2, 1])
            with col1:
                st.write(f"**{pd_doc.ingested.file_name}**")
            with col2:
                doc_type_display = cls.doc_type_display if cls else "Other"
                st.write(f"{doc_type_display}")
            with col3:
                conf = cls.confidence if cls else 0.0
                doc_type = cls.doc_type if cls else "other"
                ev_score = get_evidence_score(doc_type)
                label = "confident" if conf > 0.8 else "uncertain"
                st.write(f"{label} ({conf:.0%}) | ISA 500: {ev_score}/10")

        st.divider()
        st.subheader("Extracted data")
        for pd in state.get("documents") or []:
            file_name = pd.ingested.file_name if pd.ingested else "?"
            doc_type_display = (
                pd.classification.doc_type_display if pd.classification else "Other"
            )
            with st.expander(f"{file_name} — {doc_type_display}"):
                if pd.extracted is None:
                    st.warning("No extracted data.")
                    continue

                # Confidence indicators
                confidence = pd.extracted.confidence or {}
                if confidence:
                    low_fields = [k for k, v in confidence.items() if v == "low"]
                    medium_fields = [k for k, v in confidence.items() if v == "medium"]
                    if low_fields:
                        st.warning(
                            f"Low-confidence fields (verify in source): {', '.join(low_fields)}"
                        )
                    if medium_fields:
                        st.info(f"Fields needing interpretation: {', '.join(medium_fields)}")

                # Quotes
                quotes = pd.extracted.quotes or []
                if quotes:
                    with st.expander("Source quotes (anti-hallucination)"):
                        for q in quotes:
                            st.caption(f'"{q}"')

                display_data = {
                    k: v for k, v in pd.extracted.raw.items()
                    if k not in ("_source", "_quotes", "_confidence")
                }
                st.json(display_data)

        # Cross-document checks
        comp = state.get("comparison")
        if comp:
            st.divider()
            st.subheader("Cross-document checks (three-way matching)")

            ok = sum(1 for m in (comp.matches or []) if m.get("severity") == "ok")
            warn = sum(1 for m in (comp.matches or []) if m.get("severity") == "warning")
            crit = sum(1 for m in (comp.matches or []) if m.get("severity") == "critical")
            miss = sum(1 for m in (comp.matches or []) if m.get("severity") == "missing")

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("OK", ok)
            mc2.metric("Warning", warn)
            mc3.metric("Critical", crit)
            mc4.metric("Missing", miss)

            for m in (comp.matches or []):
                sev = m.get("severity", "ok")
                msg = m.get("message", "") or m.get("field", "")
                if sev == "critical":
                    st.error(f"CRITICAL: {msg}")
                elif sev == "warning":
                    st.warning(f"WARNING: {msg}")
                elif sev == "missing":
                    st.info(f"MISSING: {msg}")

            if comp.summary:
                st.caption(comp.summary)

        # Risks — split rule-based vs AI observations
        risks = state.get("risks") or []
        basic = [r for r in risks if r.kind != "llm_analysis" and r.severity != "info"]
        info_r = [r for r in risks if r.severity == "info"]
        ai_r = [r for r in risks if r.kind == "llm_analysis"]

        if basic or info_r or ai_r:
            st.divider()

        if basic:
            st.subheader("Risks (rule-based)")
            st.caption("Deterministic checks — math, logic, plausibility, regulations.")
            by_sev = defaultdict(list)
            for r in basic:
                by_sev[r.severity].append(r)
            for sev_label, sev_key in (("HIGH", "high"), ("MEDIUM", "medium"),
                                       ("LOW", "low")):
                items = by_sev.get(sev_key, [])
                if not items:
                    continue
                for r in items:
                    label = f"**{sev_label}: {r.description}**"
                    if r.rationale:
                        label += f"\n\n*Rationale:* {r.rationale}"
                    if r.regulation:
                        label += f"\n\n*Regulation:* {r.regulation}"
                    if sev_key == "high":
                        st.error(label)
                    elif sev_key == "medium":
                        st.warning(label)
                    else:
                        st.info(label)

        if ai_r:
            st.subheader("AI observations")
            st.caption(
                "LLM-based analysis — contextual patterns, unusual relationships. "
                "Verify against the source before making decisions."
            )
            for r in ai_r:
                label = r.description
                if r.rationale:
                    label += f"\n\n*Rationale:* {r.rationale}"
                if r.severity == "high":
                    st.error(f"**HIGH:** {label}")
                elif r.severity == "medium":
                    st.warning(f"**MEDIUM:** {label}")
                else:
                    st.info(f"**LOW:** {label}")

        if info_r and not basic and not ai_r:
            st.subheader("Information")
            for r in info_r:
                st.info(r.description)

        if not risks:
            st.divider()
            st.success("No risk indicators found.")

        # Package-level analysis — only on demo packages (opt-in)
        insights = state.get("package_insights")
        if insights is not None:
            st.divider()
            st.subheader("Package-level analysis")
            st.caption(
                "Beyond the automatic pipeline, the AI also reviews the full document "
                "package together from a cross-doc perspective. It looks for patterns "
                "visible only when the documents are reviewed together."
            )

            if insights.executive_summary:
                st.markdown("**Executive summary**")
                st.write(insights.executive_summary)

            if insights.findings:
                st.markdown("**Package-level risks**")
                for f in insights.findings:
                    sev = (f.get("severity") or f.get("sulyossag") or "low").lower()
                    description = f.get("description") or f.get("leiras", "")
                    rationale = f.get("rationale") or f.get("indoklas", "")
                    affected = f.get("affected_documents") or f.get("erinto_dokumentumok") or []

                    label = description
                    if rationale:
                        label += f"\n\n*Rationale:* {rationale}"
                    if affected:
                        label += f"\n\n*Affected documents:* {', '.join(affected)}"

                    if sev in ("high", "magas"):
                        st.error(f"**HIGH:** {label}")
                    elif sev in ("medium", "kozepes", "közepes"):
                        st.warning(f"**MEDIUM:** {label}")
                    else:
                        st.info(f"**LOW:** {label}")

            if insights.key_observations:
                st.markdown("**Key observations**")
                for obs in insights.key_observations:
                    st.write(f"- {obs}")


# =============================================================================
# TAB 3: Chat
# =============================================================================

with tab_chat:
    st.subheader("Ask about your documents")
    if st.session_state.pipeline_state is None:
        st.info("Upload and process documents to use the chat.")
    else:
        st.caption(
            "Agentic mode — the AI uses tools to answer "
            "(search, extraction, comparison, validation)."
        )

        # History
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("sources"):
                    with st.expander("Sources"):
                        for src in msg["sources"]:
                            st.write(f"- {src}")

        if prompt := st.chat_input("Ask anything about the uploaded documents..."):
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            llm = get_chat_model()
            chat_graph = build_chat_graph(llm, st.session_state.tool_context)

            with st.chat_message("assistant"):
                with st.spinner("Analyzing..."):
                    try:
                        result_state = run_async(chat_graph.ainvoke({
                            "messages": [HumanMessage(content=prompt)],
                        }))
                        answer = result_state.get("final_answer", "(empty answer)")
                        sources = result_state.get("sources_cited") or []
                    except Exception as exc:
                        answer = f"Chat error: {exc}"
                        sources = []
                st.markdown(answer)
                if sources:
                    with st.expander("Sources"):
                        for src in sources:
                            st.write(f"- {src}")

            st.session_state.chat_history.append({
                "role": "assistant",
                "content": answer,
                "sources": sources,
            })


# =============================================================================
# TAB 4: DD Assistant
# =============================================================================

with tab_dd:
    st.subheader("Due Diligence assistant")
    st.caption(
        "Contract portfolio analysis from an acquisition / DD perspective: "
        "near-term expirations, change-of-control clauses, GDPR risks, monthly "
        "obligations and critical red flags. Multi-agent supervisor "
        "(audit + legal + compliance + financial)."
    )

    state = st.session_state.pipeline_state
    if state is None:
        st.info("Upload and process contracts to start a DD analysis.")
    else:
        contracts = [
            d for d in (state.get("documents") or [])
            if d.classification and d.classification.doc_type == "contract"
        ]
        if not contracts:
            st.warning(
                f"Of the {len(state.get('documents') or [])} processed documents "
                "none are contracts. The DD assistant operates on contract-type "
                "documents only. Try the demo package."
            )
        else:
            st.success(f"{len(contracts)} contracts in the portfolio.")

            if st.button("Start DD analysis", type="primary"):
                try:
                    dd_graph = build_dd_graph(llm=get_chat_model())
                    with st.spinner("Multi-agent supervisor running..."):
                        dd_state = run_async(dd_graph.ainvoke({"documents": contracts}))
                    state["dd_report"] = dd_state.get("dd_report")
                    st.session_state.dd_contracts_summary = dd_state.get("contracts") or []
                    st.session_state.pipeline_state = state
                    st.rerun()
                except Exception as exc:
                    st.error(f"DD analysis error: {exc}")
                    with st.expander("Developer details (full traceback)"):
                        st.code(traceback.format_exc(), language="python")

            report = state.get("dd_report")
            contracts_summary = st.session_state.dd_contracts_summary

            if report is not None:
                st.divider()
                st.subheader("Executive summary")
                st.write(report.executive_summary)

                mc1, mc2, mc3, mc4 = st.columns(4)
                mc1.metric("Contracts", report.contract_count)
                mc2.metric("High-risk", len(report.high_risk_contracts))
                mc3.metric("Expiring soon (12 mo)", len(report.expiring_soon))
                mc4.metric("Top red flags", len(report.top_red_flags))

                if report.total_monthly_obligations:
                    st.subheader("Monthly obligations (estimated)")
                    obl_cols = st.columns(min(len(report.total_monthly_obligations), 4))
                    for col, (cur, amt) in zip(
                        obl_cols, report.total_monthly_obligations.items(), strict=False
                    ):
                        col.metric(cur, f"{amt:,.0f}")

                if report.top_red_flags:
                    st.subheader("Top red flags")
                    for i, flag in enumerate(report.top_red_flags, start=1):
                        st.error(f"{i}. {flag}")

                if report.expiring_soon:
                    st.subheader("Expiring soon (within 12 months)")
                    for fname in report.expiring_soon:
                        st.warning(f"- {fname}")

                if contracts_summary:
                    st.subheader("Contract details")
                    for c in contracts_summary:
                        with st.expander(
                            f"{c.file_name} — {c.risk_level.upper()} risk"
                        ):
                            st.write(f"**Type:** {c.contract_type}")
                            if c.parties:
                                st.write(f"**Parties:** {', '.join(c.parties)}")
                            if c.effective_date or c.expiry_date:
                                st.write(
                                    f"**Validity:** {c.effective_date or '?'} — "
                                    f"{c.expiry_date or '?'}"
                                )
                            if c.total_value:
                                st.write(
                                    f"**Value:** {c.total_value:,.0f} {c.currency}"
                                )
                            if c.monthly_fee:
                                st.write(
                                    f"**Monthly fee:** {c.monthly_fee:,.0f} {c.monthly_fee_currency}"
                                )
                            if c.risk_elements:
                                st.write("**Risk elements:**")
                                for k in c.risk_elements:
                                    st.write(f"- {k}")
                            if c.red_flags:
                                st.write("**Red flags:**")
                                for p in c.red_flags:
                                    st.write(f"- {p}")


# =============================================================================
# TAB 5: Report
# =============================================================================

with tab_report:
    state = st.session_state.pipeline_state
    report = (state or {}).get("report") or {} if state else {}

    if not state or not report:
        st.info("Upload and process documents to generate a report.")
    else:
        st.subheader("Report")
        if report.get("generated_at"):
            st.write(f"**Generated at:** {report['generated_at']}")
        st.write(f"**Document count:** {report.get('document_count', 0)}")

        # Executive summary (LLM)
        if report.get("executive_summary"):
            st.subheader("Executive summary")
            st.write(report["executive_summary"])

        # Cross-document section
        comp = report.get("comparison")
        if comp:
            st.subheader("Cross-document checks")
            matches = comp.get("matches") or []
            ok = sum(1 for m in matches if m.get("severity") == "ok")
            warn = sum(1 for m in matches if m.get("severity") == "warning")
            crit = sum(1 for m in matches if m.get("severity") == "critical")
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("OK", ok)
            mc2.metric("Warning", warn)
            mc3.metric("Critical", crit)

        # Risks split — rule-based vs AI observations
        risk_buckets = report.get("risks") or {}
        all_risks = (
            (risk_buckets.get("high") or [])
            + (risk_buckets.get("medium") or [])
            + (risk_buckets.get("low") or [])
            + (risk_buckets.get("info") or [])
        )

        if all_risks:
            basic_r = [r for r in all_risks if r.get("kind") != "llm_analysis"]
            ai_r = [r for r in all_risks if r.get("kind") == "llm_analysis"]

            if basic_r:
                st.subheader("Risks (rule-based)")
                for r in basic_r:
                    sev = r.get("severity", "low")
                    description = r.get("description", "")
                    if sev == "high":
                        st.error(f"HIGH: {description}")
                    elif sev == "medium":
                        st.warning(f"MEDIUM: {description}")
                    elif sev == "info":
                        st.info(f"INFO: {description}")
                    else:
                        st.info(f"LOW: {description}")

            if ai_r:
                st.subheader("AI observations")
                st.caption("Verify against the source before making decisions.")
                for r in ai_r:
                    sev = r.get("severity", "low")
                    description = r.get("description", "")
                    rationale = r.get("rationale", "")
                    label = description if not rationale else f"{description} — {rationale}"
                    if sev == "high":
                        st.error(f"HIGH: {label}")
                    elif sev == "medium":
                        st.warning(f"MEDIUM: {label}")
                    else:
                        st.info(f"LOW: {label}")

        # Package-level analysis section
        package_section = report.get("package_insights")
        if package_section:
            st.divider()
            st.subheader("Package-level analysis")
            st.caption(
                "Beyond the automatic pipeline, the AI reviewed the full document "
                "package as a whole from a cross-doc perspective."
            )
            if package_section.get("executive_summary"):
                st.markdown("**Executive summary**")
                st.write(package_section["executive_summary"])

            package_findings = package_section.get("findings") or []
            if package_findings:
                st.markdown("**Package-level risks**")
                for f in package_findings:
                    sev = (f.get("severity") or f.get("sulyossag") or "low").lower()
                    description = f.get("description") or f.get("leiras", "")
                    rationale = f.get("rationale") or f.get("indoklas", "")
                    affected = f.get("affected_documents") or f.get("erinto_dokumentumok") or []

                    label = description
                    if rationale:
                        label += f"\n\n*Rationale:* {rationale}"
                    if affected:
                        label += f"\n\n*Affected documents:* {', '.join(affected)}"

                    if sev in ("high", "magas"):
                        st.error(f"**HIGH:** {label}")
                    elif sev in ("medium", "kozepes", "közepes"):
                        st.warning(f"**MEDIUM:** {label}")
                    else:
                        st.info(f"**LOW:** {label}")

            observations = package_section.get("key_observations") or []
            if observations:
                st.markdown("**Key observations**")
                for obs in observations:
                    st.write(f"- {obs}")

        # DD analysis section
        dd_section = report.get("dd_analysis")
        if dd_section:
            st.divider()
            st.subheader("Due Diligence analysis")
            st.caption("Contract portfolio analysis from an acquisition / DD perspective.")

            if dd_section.get("executive_summary"):
                st.markdown("**Executive summary**")
                st.write(dd_section["executive_summary"])

            red_flags = dd_section.get("top_red_flags") or []
            if red_flags:
                st.markdown("**Top red flags**")
                for flag in red_flags:
                    st.error(flag)

            contracts_list = dd_section.get("contracts") or []
            if contracts_list:
                st.markdown("**Per-contract risk level**")
                for c in contracts_list:
                    if hasattr(c, "model_dump"):
                        c = c.model_dump()
                    level = c.get("risk_level") or c.get("kockazati_szint", "low")
                    file_name = c.get("file_name", "")
                    contract_type = c.get("contract_type") or c.get("szerzodes_tipusa", "")
                    parties = ", ".join(c.get("parties") or c.get("felek") or [])
                    label = f"{file_name} ({contract_type})"
                    if parties:
                        label += f" — Parties: {parties}"
                    if level in ("high", "magas"):
                        st.error(f"**HIGH:** {label}")
                    elif level in ("medium", "kozepes", "közepes"):
                        st.warning(f"**MEDIUM:** {label}")
                    else:
                        st.info(f"**LOW:** {label}")

            obligations = dd_section.get("total_monthly_obligations") or {}
            if obligations:
                st.markdown("**Monthly obligations (estimated)**")
                obl_cols = st.columns(min(len(obligations), 4))
                for col, (currency, amount) in zip(
                    obl_cols, obligations.items(), strict=False
                ):
                    col.metric(currency, f"{amount:,.0f}")

        # JSON view (debug)
        st.divider()
        with st.expander("JSON view (raw)"):
            st.json(report)

        # Export
        st.subheader("Export")
        col_json, col_docx = st.columns(2)
        with col_json:
            report_json = json.dumps(report, ensure_ascii=False, indent=2, default=str)
            st.download_button(
                label="Download report (JSON)",
                data=report_json,
                file_name=f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                mime="application/json",
                help="Raw data in JSON form — for machine processing or archival.",
            )

        with col_docx:
            if st.button("Generate DOCX report", type="primary"):
                try:
                    docx_bytes = build_docx_sync(state)
                    st.session_state.docx_bytes = docx_bytes
                    st.success("DOCX ready — click the download button.")
                except Exception as exc:
                    st.error(f"DOCX generation error: {exc}")
                    with st.expander("Developer details"):
                        st.code(traceback.format_exc(), language="python")

            if st.session_state.docx_bytes:
                st.download_button(
                    label="Download DOCX",
                    data=st.session_state.docx_bytes,
                    file_name=f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    help="Formatted Word document — for printing, presentations, or client handoff.",
                )


# ---------------------------------------------------------------------------
# Applied standards footer (dynamic — only the actually triggered standards)
# ---------------------------------------------------------------------------

if st.session_state.pipeline_state:
    _state = st.session_state.pipeline_state
    _risks = _state.get("risks") or []
    if _risks:
        from domain_checks import get_applied_standards
        _standards = get_applied_standards(_risks)
        if _standards:
            st.divider()
            st.caption(
                "**Applied standards and methods:** "
                + " | ".join(_standards)
            )


# ---------------------------------------------------------------------------
# Footer (MIT-licensed; see LICENSE)
# ---------------------------------------------------------------------------

st.divider()
st.caption(
    "Built by Team CsimpiCsirkek for the AMD Developer Hackathon × lablab.ai (2026). "
    "MIT licensed — see LICENSE. Powered by LangGraph + Qwen on AMD MI300X."
)
