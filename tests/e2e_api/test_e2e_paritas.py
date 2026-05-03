"""10-csoportos E2E API paritás-teszt — a `prototype-agentic/test_e2e.py` ekvivalense.

Közvetlenül a `pipeline_graph.ainvoke()`-ot hívja (UI nélkül). Per-csoport JSON
output a `tests/e2e_api/results/` mappában, plusz determinisztikus assertek és
Claude AI-validáció.

Csoportok:
  01 -- Egyedi számlák (5 fájl: 3 HU + 1 EN intra-EU + 1 DE)
  02 -- Egyedi szerződések (4 fájl: NDA + MSSA + IT support + leasing)
  03 -- Pénzügyi kimutatások (2 fájl: HU eredménykim + EN cash flow IFRS)
  04 -- Multi-doc three-way matching (3 PDF: PO + DN + INV)
  05 -- Adversarial egyenként (4 fájl: math/incomplete/bilingual/date)
  06 -- Adversarial kombinált (mind a 4 együtt)
  07 -- Audit demo (3 számla, +50% árnövekedés)
  08 -- DD demo (NDA + MSSA + amendment, 3 piros zászló)
  09 -- Compliance demo (2 szerz, GDPR-aszimmetria)
  10 -- 14 chat kérdés (8 multi_doc + 3 audit + 3 compliance)

Futtatás:
  pytest tests/e2e_api/ -v -s

Idő: ~10-15 perc Claude Haiku-val.
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from tests.e2e_api.conftest import RESULTS_DIR, TEST_DATA
from tests.e2e_api.expected_findings import CHAT_SCENARIOS, EXPECTED_FINDINGS


# ---------------------------------------------------------------------------
# Lazy import — csak akkor töltünk graph-ot ha a teszt valóban fut
# ---------------------------------------------------------------------------


def _build_pipeline():
    from graph.pipeline_graph import build_pipeline_graph
    from providers import get_chat_model
    from store import HybridStore

    store = HybridStore()
    llm = get_chat_model()
    graph = build_pipeline_graph(store, llm=llm)
    return graph, store, llm


def _build_package_insights():
    from graph.package_insights_graph import build_package_insights_graph
    from providers import get_chat_model
    return build_package_insights_graph(llm=get_chat_model())


def _build_dd():
    from graph.dd_graph import build_dd_graph
    from providers import get_chat_model
    return build_dd_graph(llm=get_chat_model())


# ---------------------------------------------------------------------------
# Helper dataclass + serializálás
# ---------------------------------------------------------------------------


@dataclass
class ParitasResult:
    test_name: str
    files: list[str]
    timestamp: str
    pipeline_seconds: float
    document_count: int
    risk_count: int
    risks: list[dict] = field(default_factory=list)
    classifications: list[dict] = field(default_factory=list)
    extracted: list[dict] = field(default_factory=list)
    comparison: dict | None = None
    package_insights: dict | None = None
    dd_report: dict | None = None
    chat_responses: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    paritas_assertions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _load_files(file_paths: list[Path]) -> list[tuple[str, bytes]]:
    return [(p.name, p.read_bytes()) for p in file_paths if p.exists()]


def _serialize_pipeline_state(state: dict) -> dict:
    out: dict[str, Any] = {}
    docs = state.get("documents") or []
    out["document_count"] = len(docs)
    out["classifications"] = [
        {
            "file_name": d.ingested.file_name if d.ingested else None,
            "doc_type": d.classification.doc_type if d.classification else None,
            "doc_type_display": d.classification.doc_type_display if d.classification else None,
            "confidence": d.classification.confidence if d.classification else None,
            "language": d.classification.language if d.classification else None,
        }
        for d in docs
    ]
    out["extracted"] = [
        {
            "file_name": d.ingested.file_name if d.ingested else None,
            "raw": d.extracted.raw if d.extracted else None,
        }
        for d in docs
    ]
    risks = state.get("risks") or []
    out["risks"] = [
        {
            "leiras": r.leiras,
            "sulyossag": r.sulyossag,
            "indoklas": r.indoklas,
            "tipus": r.tipus,
            "jogszabaly": r.jogszabaly,
            "erinto_dokumentum": r.erinto_dokumentum,
        }
        for r in risks
    ]
    out["risk_count"] = len(risks)
    comp = state.get("comparison")
    if comp is not None:
        out["comparison"] = comp.model_dump() if hasattr(comp, "model_dump") else dict(comp)
    pkg = state.get("package_insights")
    if pkg is not None:
        out["package_insights"] = pkg.model_dump() if hasattr(pkg, "model_dump") else dict(pkg)
    dd = state.get("dd_report")
    if dd is not None:
        out["dd_report"] = dd.model_dump() if hasattr(dd, "model_dump") else dict(dd)
    out["pipeline_seconds"] = state.get("processing_seconds", 0.0)
    return out


def _save_result(name: str, data: ParitasResult | dict) -> None:
    payload = data.to_dict() if isinstance(data, ParitasResult) else data
    out_path = RESULTS_DIR / f"{name}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# Determinisztikus paritás-checkek
# ---------------------------------------------------------------------------


def _flatten_state_text(serialized: dict) -> str:
    parts: list[str] = []
    for r in serialized.get("risks", []):
        parts.append(r.get("leiras", ""))
        parts.append(r.get("indoklas", ""))
    comp = serialized.get("comparison") or {}
    if isinstance(comp, dict):
        for m in comp.get("matches", []):
            if isinstance(m, dict):
                parts.append(str(m.get("message", "")))
                parts.append(str(m.get("field", "")))
    pkg = serialized.get("package_insights") or {}
    if isinstance(pkg, dict):
        parts.append(str(pkg.get("executive_summary", "")))
        for f in pkg.get("findings", []) or []:
            if isinstance(f, dict):
                parts.append(str(f.get("leiras", "")))
                parts.append(str(f.get("indoklas", "")))
        for o in pkg.get("key_observations", []) or []:
            parts.append(str(o))
    dd = serialized.get("dd_report") or {}
    if isinstance(dd, dict):
        parts.append(str(dd.get("executive_summary", "")))
        for flag in dd.get("top_red_flags", []) or []:
            parts.append(str(flag))
    return " ".join(parts).lower()


def _check_must_contain(text: str, expected: dict) -> list[dict]:
    results = []
    for kw in expected.get("must_contain_keywords", []):
        results.append({
            "type": "must_contain_keyword",
            "keyword": kw,
            "passed": kw.lower() in text,
        })
    if expected.get("must_contain_any_of"):
        keywords = expected["must_contain_any_of"]
        any_passed = any(kw.lower() in text for kw in keywords)
        results.append({
            "type": "must_contain_any_of",
            "keywords": keywords,
            "passed": any_passed,
        })
    for kw in expected.get("must_not_contain", []):
        results.append({
            "type": "must_not_contain",
            "keyword": kw,
            "passed": kw.lower() not in text,
        })
    return results


def _check_risk_count(serialized: dict, expected: dict) -> list[dict]:
    actual = serialized.get("risk_count", 0)
    results = []
    if "expected_risks_min" in expected:
        results.append({
            "type": "risk_count_min",
            "min": expected["expected_risks_min"],
            "actual": actual,
            "passed": actual >= expected["expected_risks_min"],
        })
    if "expected_risks_max" in expected:
        results.append({
            "type": "risk_count_max",
            "max": expected["expected_risks_max"],
            "actual": actual,
            "passed": actual <= expected["expected_risks_max"],
        })
    return results


def _check_severity(serialized: dict, expected: dict) -> list[dict]:
    if "expected_severity_max" not in expected:
        return []
    sev_order = {"info": 0, "alacsony": 1, "kozepes": 2, "magas": 3}
    max_allowed = sev_order.get(expected["expected_severity_max"], 3)
    actual_max = 0
    actual_max_label = "info"
    for r in serialized.get("risks", []):
        s = r.get("sulyossag") or "info"
        if sev_order.get(s, 0) > actual_max:
            actual_max = sev_order.get(s, 0)
            actual_max_label = s
    return [{
        "type": "severity_max",
        "max_allowed": expected["expected_severity_max"],
        "actual_max": actual_max_label,
        "passed": actual_max <= max_allowed,
    }]


def _check_doc_type(serialized: dict, expected: dict) -> list[dict]:
    results = []
    if "expected_doc_type" in expected:
        actual = (serialized.get("classifications") or [{}])[0].get("doc_type")
        results.append({
            "type": "doc_type",
            "expected": expected["expected_doc_type"],
            "actual": actual,
            "passed": actual == expected["expected_doc_type"],
        })
    if "expected_doc_types" in expected:
        actual_types = sorted(c.get("doc_type") for c in serialized.get("classifications", []))
        expected_types = sorted(expected["expected_doc_types"])
        results.append({
            "type": "doc_types_set",
            "expected": expected_types,
            "actual": actual_types,
            "passed": actual_types == expected_types,
        })
    if "expected_doc_types_all" in expected:
        target = expected["expected_doc_types_all"]
        all_match = all(
            c.get("doc_type") == target
            for c in serialized.get("classifications", [])
        )
        results.append({
            "type": "doc_types_all",
            "expected_all": target,
            "passed": all_match,
        })
    return results


def _evaluate_paritas(serialized: dict, expected: dict) -> tuple[list[dict], bool]:
    assertions = []
    assertions.extend(_check_doc_type(serialized, expected))
    assertions.extend(_check_risk_count(serialized, expected))
    assertions.extend(_check_severity(serialized, expected))
    text = _flatten_state_text(serialized)
    assertions.extend(_check_must_contain(text, expected))
    overall_pass = all(a.get("passed", False) for a in assertions)
    return assertions, overall_pass


def _run_pipeline_for_files(files: list[Path]) -> tuple[dict, dict, Any]:
    graph, store, llm = _build_pipeline()
    file_tuples = _load_files(files)
    state = asyncio.run(graph.ainvoke({"files": file_tuples}))
    return _serialize_pipeline_state(state), state, store


# ===========================================================================
# 01. Egyedi számlák — 5 fájl
# ===========================================================================


@pytest.mark.e2e_paritas
@pytest.mark.parametrize("file_rel", [
    "szamlak/bs-2026-001.pdf",
    "szamlak/bs-2026-002.pdf",
    "szamlak/bs-2026-003.pdf",
    "szamlak/nl-inv-2026-0001.pdf",
    "szamlak/bk-r-2026-0001.pdf",
])
def test_01_single_invoices(file_rel):
    expected = EXPECTED_FINDINGS[file_rel]
    pdf = TEST_DATA / file_rel
    assert pdf.exists(), f"Hiányzik: {pdf}"

    t0 = time.time()
    serialized, _, _ = _run_pipeline_for_files([pdf])
    elapsed = time.time() - t0

    assertions, overall = _evaluate_paritas(serialized, expected)
    result = ParitasResult(
        test_name=f"01_single_{pdf.stem}",
        files=[file_rel],
        timestamp=datetime.now().isoformat(),
        pipeline_seconds=elapsed,
        document_count=serialized["document_count"],
        risk_count=serialized["risk_count"],
        risks=serialized["risks"],
        classifications=serialized["classifications"],
        extracted=serialized["extracted"],
        paritas_assertions=assertions,
    )
    _save_result(f"01_single_{pdf.stem}", result)
    assert overall, f"Paritás FAIL: {[a for a in assertions if not a.get('passed')]}"


# ===========================================================================
# 02. Egyedi szerződések — 4 fájl
# ===========================================================================


@pytest.mark.e2e_paritas
@pytest.mark.parametrize("file_rel", [
    "szerzodesek/bl-nt-nda-2026.pdf",
    "szerzodesek/pt-dp-mssa-2026.pdf",
    "szerzodesek/mbk-it-fa-2026.pdf",
    "szerzodesek/df-lc-2026.pdf",
])
def test_02_single_contracts(file_rel):
    expected = EXPECTED_FINDINGS[file_rel]
    pdf = TEST_DATA / file_rel
    assert pdf.exists()

    t0 = time.time()
    serialized, _, _ = _run_pipeline_for_files([pdf])
    elapsed = time.time() - t0

    assertions, overall = _evaluate_paritas(serialized, expected)
    result = ParitasResult(
        test_name=f"02_contract_{pdf.stem}",
        files=[file_rel],
        timestamp=datetime.now().isoformat(),
        pipeline_seconds=elapsed,
        document_count=serialized["document_count"],
        risk_count=serialized["risk_count"],
        risks=serialized["risks"],
        classifications=serialized["classifications"],
        extracted=serialized["extracted"],
        paritas_assertions=assertions,
    )
    _save_result(f"02_contract_{pdf.stem}", result)
    assert overall, f"Paritás FAIL: {[a for a in assertions if not a.get('passed')]}"


# ===========================================================================
# 03. Pénzügyi kimutatások — 2 fájl
# ===========================================================================


@pytest.mark.e2e_paritas
@pytest.mark.parametrize("file_rel", [
    "penzugyi_riportok/fin-hu-er-2025.pdf",
    "penzugyi_riportok/fin-en-cf-2025.pdf",
])
def test_03_financial_reports(file_rel):
    expected = EXPECTED_FINDINGS[file_rel]
    pdf = TEST_DATA / file_rel
    assert pdf.exists()

    t0 = time.time()
    serialized, _, _ = _run_pipeline_for_files([pdf])
    elapsed = time.time() - t0

    assertions, overall = _evaluate_paritas(serialized, expected)
    result = ParitasResult(
        test_name=f"03_financial_{pdf.stem}",
        files=[file_rel],
        timestamp=datetime.now().isoformat(),
        pipeline_seconds=elapsed,
        document_count=serialized["document_count"],
        risk_count=serialized["risk_count"],
        risks=serialized["risks"],
        classifications=serialized["classifications"],
        extracted=serialized["extracted"],
        paritas_assertions=assertions,
    )
    _save_result(f"03_financial_{pdf.stem}", result)
    assert overall, f"Paritás FAIL: {[a for a in assertions if not a.get('passed')]}"


# ===========================================================================
# 04. Multi-doc three-way matching — HI-100 hiány
# ===========================================================================


@pytest.mark.e2e_paritas
def test_04_multi_doc():
    expected = EXPECTED_FINDINGS["multi_doc/__triplet__"]
    files = [
        TEST_DATA / "multi_doc" / "epkft-po-2026-0412.pdf",
        TEST_DATA / "multi_doc" / "epkft-dn-2026-0415.pdf",
        TEST_DATA / "multi_doc" / "epkft-inv-2026-0418.pdf",
    ]
    for f in files:
        assert f.exists()

    t0 = time.time()
    serialized, state, _ = _run_pipeline_for_files(files)
    elapsed = time.time() - t0

    assertions, overall = _evaluate_paritas(serialized, expected)
    result = ParitasResult(
        test_name="04_multi_doc_cross_check",
        files=[str(f.relative_to(TEST_DATA)) for f in files],
        timestamp=datetime.now().isoformat(),
        pipeline_seconds=elapsed,
        document_count=serialized["document_count"],
        risk_count=serialized["risk_count"],
        risks=serialized["risks"],
        classifications=serialized["classifications"],
        extracted=serialized["extracted"],
        comparison=serialized.get("comparison"),
        paritas_assertions=assertions,
    )
    _save_result("04_multi_doc_cross_check", result)
    critical_failed = [
        a for a in assertions
        if not a.get("passed") and a.get("type") in ("doc_types_set", "must_contain_keyword", "must_contain_any_of")
    ]
    assert not critical_failed, f"Kritikus paritás FAIL: {critical_failed}"


# ===========================================================================
# 05. Adversarial egyenként — 4 fájl
# ===========================================================================


@pytest.mark.e2e_paritas
@pytest.mark.parametrize("file_rel", [
    "adversarial/adv-inv-2026-0001.pdf",
    "adversarial/adv-ctr-2026-001.pdf",
    "adversarial/adv-ctr-2026-002.pdf",
    "adversarial/adv-ctr-2026-003.pdf",
])
def test_05_adversarial(file_rel):
    expected = EXPECTED_FINDINGS[file_rel]
    pdf = TEST_DATA / file_rel
    assert pdf.exists()

    t0 = time.time()
    serialized, _, _ = _run_pipeline_for_files([pdf])
    elapsed = time.time() - t0

    assertions, overall = _evaluate_paritas(serialized, expected)
    result = ParitasResult(
        test_name=f"05_adversarial_{pdf.stem}",
        files=[file_rel],
        timestamp=datetime.now().isoformat(),
        pipeline_seconds=elapsed,
        document_count=serialized["document_count"],
        risk_count=serialized["risk_count"],
        risks=serialized["risks"],
        classifications=serialized["classifications"],
        extracted=serialized["extracted"],
        paritas_assertions=assertions,
    )
    _save_result(f"05_adversarial_{pdf.stem}", result)
    critical_failed = [
        a for a in assertions
        if not a.get("passed") and a.get("type") in ("must_contain_keyword", "must_contain_any_of")
    ]
    assert not critical_failed, f"Adversarial finding hiányzik: {critical_failed}"


# ===========================================================================
# 06. Adversarial kombinált — mind a 4 együtt
# ===========================================================================


@pytest.mark.e2e_paritas
def test_06_adversarial_combined():
    expected = EXPECTED_FINDINGS["adversarial/__combined__"]
    files = sorted((TEST_DATA / "adversarial").glob("*.pdf"))
    assert len(files) == 4

    t0 = time.time()
    serialized, _, _ = _run_pipeline_for_files(files)
    elapsed = time.time() - t0

    assertions, overall = _evaluate_paritas(serialized, expected)
    result = ParitasResult(
        test_name="06_adversarial_combined",
        files=[str(f.relative_to(TEST_DATA)) for f in files],
        timestamp=datetime.now().isoformat(),
        pipeline_seconds=elapsed,
        document_count=serialized["document_count"],
        risk_count=serialized["risk_count"],
        risks=serialized["risks"],
        classifications=serialized["classifications"],
        extracted=serialized["extracted"],
        paritas_assertions=assertions,
    )
    _save_result("06_adversarial_combined", result)
    critical_failed = [
        a for a in assertions
        if not a.get("passed") and a.get("type") in ("must_contain_keyword",)
    ]
    assert not critical_failed, f"Cross-doc finding hiányzik: {critical_failed}"


# ===========================================================================
# 07-09. Demo csomagok
# ===========================================================================


def _run_demo_package(pkg_key: str) -> tuple[dict, list[Path]]:
    pkg_dir = TEST_DATA / "demo_csomagok" / pkg_key
    files = sorted(pkg_dir.glob("*.pdf"))
    assert files, f"Üres demo csomag: {pkg_key}"

    graph, store, llm = _build_pipeline()
    state = asyncio.run(graph.ainvoke({"files": _load_files(files)}))

    pkg_type_map = {"audit_demo": "audit", "dd_demo": "dd", "compliance_demo": "compliance"}
    pkg_type = pkg_type_map.get(pkg_key, "general")
    pkg_graph = _build_package_insights()
    pkg_state = asyncio.run(pkg_graph.ainvoke({
        "documents": state.get("documents") or [],
        "package_type": pkg_type,
    }))
    # A graph state-ben a kulcs `final_insights` (lásd app/main.py:218); átmappeljük
    state["package_insights"] = pkg_state.get("final_insights")

    contracts = [
        d for d in (state.get("documents") or [])
        if d.classification and d.classification.doc_type == "szerzodes"
    ]
    if contracts:
        dd_graph = _build_dd()
        dd_state = asyncio.run(dd_graph.ainvoke({"documents": contracts}))
        state["dd_report"] = dd_state.get("dd_report")

    return _serialize_pipeline_state(state), files


@pytest.mark.e2e_paritas
def test_07_audit_demo():
    expected = EXPECTED_FINDINGS["demo_csomagok/audit_demo/__package__"]
    t0 = time.time()
    serialized, files = _run_demo_package("audit_demo")
    elapsed = time.time() - t0

    assertions, overall = _evaluate_paritas(serialized, expected)
    result = ParitasResult(
        test_name="07_audit_demo",
        files=[str(f.relative_to(TEST_DATA)) for f in files],
        timestamp=datetime.now().isoformat(),
        pipeline_seconds=elapsed,
        document_count=serialized["document_count"],
        risk_count=serialized["risk_count"],
        risks=serialized["risks"],
        classifications=serialized["classifications"],
        extracted=serialized["extracted"],
        package_insights=serialized.get("package_insights"),
        paritas_assertions=assertions,
    )
    _save_result("07_audit_demo", result)
    critical_failed = [
        a for a in assertions
        if not a.get("passed") and a.get("type") in ("must_contain_any_of", "doc_types_all")
    ]
    assert not critical_failed, f"Audit demo paritás FAIL: {critical_failed}"


@pytest.mark.e2e_paritas
def test_08_dd_demo():
    expected = EXPECTED_FINDINGS["demo_csomagok/dd_demo/__package__"]
    t0 = time.time()
    serialized, files = _run_demo_package("dd_demo")
    elapsed = time.time() - t0

    assertions, overall = _evaluate_paritas(serialized, expected)
    result = ParitasResult(
        test_name="08_dd_demo",
        files=[str(f.relative_to(TEST_DATA)) for f in files],
        timestamp=datetime.now().isoformat(),
        pipeline_seconds=elapsed,
        document_count=serialized["document_count"],
        risk_count=serialized["risk_count"],
        risks=serialized["risks"],
        classifications=serialized["classifications"],
        extracted=serialized["extracted"],
        package_insights=serialized.get("package_insights"),
        dd_report=serialized.get("dd_report"),
        paritas_assertions=assertions,
    )
    _save_result("08_dd_demo", result)
    critical_failed = [
        a for a in assertions
        if not a.get("passed") and a.get("type") in ("must_contain_any_of",)
    ]
    assert not critical_failed, f"DD demo paritás FAIL: {critical_failed}"


@pytest.mark.e2e_paritas
def test_09_compliance_demo():
    expected = EXPECTED_FINDINGS["demo_csomagok/compliance_demo/__package__"]
    t0 = time.time()
    serialized, files = _run_demo_package("compliance_demo")
    elapsed = time.time() - t0

    assertions, overall = _evaluate_paritas(serialized, expected)
    result = ParitasResult(
        test_name="09_compliance_demo",
        files=[str(f.relative_to(TEST_DATA)) for f in files],
        timestamp=datetime.now().isoformat(),
        pipeline_seconds=elapsed,
        document_count=serialized["document_count"],
        risk_count=serialized["risk_count"],
        risks=serialized["risks"],
        classifications=serialized["classifications"],
        extracted=serialized["extracted"],
        package_insights=serialized.get("package_insights"),
        paritas_assertions=assertions,
    )
    _save_result("09_compliance_demo", result)
    critical_failed = [
        a for a in assertions
        if not a.get("passed") and a.get("type") in ("must_contain_any_of", "must_contain_keyword")
    ]
    assert not critical_failed, f"Compliance demo paritás FAIL: {critical_failed}"


# ===========================================================================
# 10. 14 chat kérdés
# ===========================================================================


def _run_chat_scenario(scenario_key: str) -> dict:
    from langchain_core.messages import AIMessage, HumanMessage

    scenario = CHAT_SCENARIOS[scenario_key]
    files = [TEST_DATA / f for f in scenario["context_files"]]
    for f in files:
        assert f.exists(), f"Hiányzik: {f}"

    graph, store, llm = _build_pipeline()
    pipeline_state = asyncio.run(graph.ainvoke({"files": _load_files(files)}))

    from tools.context import ChatToolContext
    tool_context = ChatToolContext(store=store)
    for d in pipeline_state.get("documents") or []:
        tool_context.add_document(d)

    from graph.chat_graph import build_chat_graph
    chat_graph = build_chat_graph(llm, tool_context)

    chat_results = []
    chat_history: list = []

    for q_def in scenario["questions"]:
        question = q_def["q"]
        try:
            chat_history.append(HumanMessage(content=question))
            chat_state = asyncio.run(chat_graph.ainvoke({"messages": chat_history}))
            answer = chat_state.get("final_answer", "")
            sources = chat_state.get("sources_cited") or []
            chat_history.append(AIMessage(content=answer))

            answer_lc = answer.lower()
            assertions = []
            must_any = q_def.get("must_contain_any_of", [])
            if must_any:
                assertions.append({
                    "type": "must_contain_any_of",
                    "keywords": must_any,
                    "passed": any(kw.lower() in answer_lc for kw in must_any),
                })
            for kw in q_def.get("must_not_contain", []):
                assertions.append({
                    "type": "must_not_contain",
                    "keyword": kw,
                    "passed": kw.lower() not in answer_lc,
                })

            chat_results.append({
                "q": question,
                "a": answer,
                "sources": sources,
                "assertions": assertions,
                "follow_up": q_def.get("follow_up", False),
            })
        except Exception as exc:
            chat_results.append({
                "q": question,
                "a": "",
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(),
            })

    return {"scenario": scenario_key, "context_files": scenario["context_files"], "qa": chat_results}


@pytest.mark.e2e_paritas
@pytest.mark.parametrize("scenario_key", list(CHAT_SCENARIOS.keys()))
def test_10_chat_scenarios(scenario_key):
    t0 = time.time()
    out = _run_chat_scenario(scenario_key)
    elapsed = time.time() - t0
    out["elapsed_seconds"] = elapsed
    out["timestamp"] = datetime.now().isoformat()
    _save_result(f"10_chat_{scenario_key}", out)

    errors = [r for r in out["qa"] if r.get("error")]
    failed = [
        r for r in out["qa"]
        if not r.get("error") and any(not a["passed"] for a in r.get("assertions", []))
    ]
    if errors or failed:
        msg = []
        if errors:
            msg.append(f"{len(errors)} chat hiba")
        if failed:
            msg.append(f"{len(failed)} kérdésre nem teljesült az assertion")
        raise AssertionError("; ".join(msg))
