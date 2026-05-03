"""Functional eval: chat questions over the full pipeline.

Uploads all test_data/ samples and runs the chat-graph through every question.
Per question:
  * pass: at least one ``expected_substrings`` token is in the answer (diacritic-tolerant)
  * tool match: every ``expected_tools`` entry is in the tool messages
  * latency_ms

CLI:  python eval/run_eval.py --llm dummy [--quick]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import HumanMessage, ToolMessage  # noqa: E402

from graph.chat_graph import build_chat_graph  # noqa: E402
from graph.pipeline_graph import build_pipeline_graph  # noqa: E402
from providers import get_chat_model, get_dummy_handle  # noqa: E402
from store import HybridStore  # noqa: E402
from tools import ChatToolContext  # noqa: E402


EVAL_DIR = Path(__file__).resolve().parent
QUESTIONS_PATH = EVAL_DIR / "questions.json"
RESULTS_MD = EVAL_DIR / "results.md"
SAMPLE_DIRS = [
    EVAL_DIR.parent / "test_data" / "invoices",
    EVAL_DIR.parent / "test_data" / "contracts",
    EVAL_DIR.parent / "test_data" / "multi_doc",
]


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _setup() -> tuple:
    """Pipeline futás → ChatToolContext kitöltése."""
    store = HybridStore()
    files = []
    for d in SAMPLE_DIRS:
        if not d.exists():
            continue
        for pdf in sorted(d.glob("*.pdf")):
            files.append((pdf.name, pdf.read_bytes()))

    if not files:
        raise RuntimeError(
            "No sample PDFs found. Run: python test_data/generate_samples.py"
        )

    if os.getenv("LLM_PROFILE", "dummy") == "dummy":
        dummy = get_dummy_handle()
        dummy.set_docs_hint([fn for fn, _ in files])

    pipeline = build_pipeline_graph(store)
    state = asyncio.run(pipeline.ainvoke({"files": files}))

    context = ChatToolContext(store=store)
    for pd in state.get("documents") or []:
        context.add_document(pd)

    return context, [fn for fn, _ in files], state


def _run_one(context: ChatToolContext, llm, question: dict) -> dict:
    chat_graph = build_chat_graph(llm, context)
    start = time.time()
    try:
        state = asyncio.run(chat_graph.ainvoke({
            "messages": [HumanMessage(content=question["question"])],
        }))
        latency_ms = (time.time() - start) * 1000
        answer = state.get("final_answer", "")
        tool_calls = [
            m.name for m in state.get("messages") or []
            if isinstance(m, ToolMessage) and m.name
        ]
    except Exception as e:
        latency_ms = (time.time() - start) * 1000
        answer = f"ERROR: {e}"
        tool_calls = []

    # Substring match (ékezet-toleráns)
    answer_norm = _normalize(answer)
    pass_subst = any(
        _normalize(s) in answer_norm
        for s in question.get("expected_substrings", [])
    )

    # Tool match
    expected_tools = set(question.get("expected_tools", []))
    actual_tools = set(tool_calls)
    tools_match = expected_tools.issubset(actual_tools) if expected_tools else True

    return {
        "id": question["id"],
        "category": question["category"],
        "question": question["question"],
        "answer": answer[:200] + ("..." if len(answer) > 200 else ""),
        "tools_called": tool_calls,
        "expected_tools": list(expected_tools),
        "tools_match": tools_match,
        "pass": pass_subst,
        "latency_ms": round(latency_ms, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", default=os.getenv("LLM_PROFILE", "dummy"),
                        choices=["claude", "ollama", "dummy"])
    parser.add_argument("--quick", action="store_true",
                        help="csak 5 kérdés (gyors smoke teszt)")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    os.environ["LLM_PROFILE"] = args.llm

    print(f"Eval init: llm={args.llm}...")
    context, filenames, _ = _setup()
    print(f"  Setup: {len(filenames)} doksi feltöltve.")

    llm = get_chat_model(args.llm)
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    if args.quick:
        seen_cat = set()
        out = []
        for q in questions:
            if q["category"] not in seen_cat:
                seen_cat.add(q["category"])
                out.append(q)
        questions = out

    print(f"\nFutás: {len(questions)} kérdés...")
    results = []
    for q in questions:
        r = _run_one(context, llm, q)
        status = "✓ PASS" if r["pass"] else "✗ FAIL"
        print(f"  {status}  [{r['category']:8}] {r['id']}: {r['answer'][:60]}...")
        results.append(r)

    # Aggregátum
    passed = sum(1 for r in results if r["pass"])
    tools_match = sum(1 for r in results if r["tools_match"])
    latencies = [r["latency_ms"] for r in results]

    by_cat: dict[str, dict] = {}
    for r in results:
        c = r["category"]
        by_cat.setdefault(c, {"pass": 0, "total": 0})
        by_cat[c]["total"] += 1
        if r["pass"]:
            by_cat[c]["pass"] += 1

    md = ["# Funkcionális ertekeles eredmenye", ""]
    md.append(f"- LLM provider: **{args.llm}**")
    md.append(f"- Osszesen: {len(results)} kerdes")
    md.append(f"- Pass rate: **{passed}/{len(results)} ({100*passed/len(results):.0f}%)**")
    md.append(f"- Tool-sorrend egyezes: {tools_match}/{len(results)}")
    md.append(f"- Latency p50: {statistics.median(latencies):.0f} ms, p95: "
              f"{sorted(latencies)[int(len(latencies)*0.95)]:.0f} ms, "
              f"max: {max(latencies):.0f} ms")
    md.append("")
    md.append("## Per-kerdes eredmenyek")
    md.append("")
    md.append("| ID | Kat. | Pass | Tools | Latency (ms) |")
    md.append("|---|---|---|---|---|")
    for r in results:
        tool_match_str = "[+]" if r["tools_match"] else "[-]"
        pass_str = "OK" if r["pass"] else "FAIL"
        tools_str = ", ".join(r["tools_called"]) or "(none)"
        md.append(f"| {r['id']} | {r['category']} | {pass_str} | {tools_str} {tool_match_str} | {r['latency_ms']:.0f} |")
    md.append("")
    md.append("## Per-kategoria")
    md.append("")
    md.append("| Kategoria | Pass | Total |")
    md.append("|---|---|---|")
    for cat, d in by_cat.items():
        md.append(f"| {cat} | {d['pass']} | {d['total']} |")

    md_text = "\n".join(md) + "\n"
    print()
    print(md_text)

    if not args.no_write:
        RESULTS_MD.write_text(md_text, encoding="utf-8")
        print(f"\nMentve: {RESULTS_MD}")


if __name__ == "__main__":
    main()
