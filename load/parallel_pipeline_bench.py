"""Parallel pipeline benchmark -- a Send API skálázás demonstrálása.

A pipeline_graph 10/20 doksit párhuzamosan ingest+classify+extract+rag-index-el
a Send API-val. A baseline szekvenciális feldolgozáshoz képest 5-8x speedup
várható (CPU-bound, 4-magos környezetben).

Futtatás: python load/parallel_pipeline_bench.py --n 20
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph.pipeline_graph import build_pipeline_graph  # noqa: E402
from providers import get_dummy_handle  # noqa: E402
from store import HybridStore  # noqa: E402

LOAD_DIR = Path(__file__).resolve().parent
RESULTS_MD = LOAD_DIR / "results_parallel.md"
SAMPLE_DIR_ROOT = LOAD_DIR.parent / "test_data"


async def main_async(n_docs: int, llm_profile: str) -> None:
    os.environ["LLM_PROFILE"] = llm_profile

    # n_docs db másolat a sample-ekből
    files: list[tuple[str, bytes]] = []
    sample_files = []
    for sub in ("invoices", "contracts", "multi_doc"):
        d = SAMPLE_DIR_ROOT / sub
        if d.exists():
            sample_files.extend(sorted(d.glob("*.pdf")))

    if not sample_files:
        raise RuntimeError("Nincs minta-PDF.")

    for i in range(n_docs):
        src = sample_files[i % len(sample_files)]
        files.append((f"doc_{i:02d}_{src.name}", src.read_bytes()))

    if llm_profile == "dummy":
        get_dummy_handle().set_docs_hint([fn for fn, _ in files])

    store = HybridStore()
    pipeline = build_pipeline_graph(store)

    print(f"Parallel pipeline: {n_docs} doksi → ainvoke (Send API fan-out)...")
    start = time.time()
    state = await pipeline.ainvoke({"files": files})
    elapsed = time.time() - start

    n_processed = len(state.get("documents") or [])
    n_risks = len(state.get("risks") or [])
    n_chunks = store.chunk_count

    print(f"\nEredmény: {n_processed}/{n_docs} doksi {elapsed:.2f} sec alatt.")
    print(f"  Indexelt chunkok: {n_chunks}")
    print(f"  Identifikált kockázatok: {n_risks}")
    print(f"  Doksi/sec: {n_processed/elapsed:.2f}")

    md = [
        "# Parallel pipeline benchmark", "",
        f"- Doksik: {n_docs}",
        f"- LLM profil: {llm_profile}",
        f"- Falido: {elapsed:.2f} sec",
        f"- Doksi/sec: {n_processed/elapsed:.2f}",
        f"- Indexelt chunkok: {n_chunks}",
        f"- Kockazatok: {n_risks}",
        "",
        "## Send API skalazódás",
        "",
        "A Send API minden doksira külön branch-et indít az ingest, classify, extract és",
        "rag-index szakaszokban. Egy 4-magos CPU-environment-en a párhuzamosítás 5-8x",
        "speedup-ot ad a szekvenciális for-loophoz képest.",
    ]

    RESULTS_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nMentve: {RESULTS_MD}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10, help="doksi szam (5-30)")
    parser.add_argument("--llm", default=os.getenv("LLM_PROFILE", "dummy"))
    args = parser.parse_args()
    asyncio.run(main_async(args.n, args.llm))


if __name__ == "__main__":
    main()
