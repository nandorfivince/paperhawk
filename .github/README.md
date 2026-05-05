<p align="center">
  <img src="https://raw.githubusercontent.com/nandorfivince/paperhawk/main/paperhawk.jpeg" alt="PaperHawk" width="900">
</p>

<h1 align="center">PaperHawk</h1>

<p align="center">
  <strong>Agentic document intelligence on AMD MI300X</strong><br>
  Multi-document due diligence with deterministic domain checks and agentic LLM workflows.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/LangGraph-0.6-green.svg" alt="LangGraph">
  <img src="https://img.shields.io/badge/AMD-MI300X-red.svg" alt="AMD MI300X">
</p>

<p align="center">
  Built for the <a href="https://lablab.ai/event/amd-developer-hackathon"><strong>AMD Developer Hackathon × lablab.ai</strong></a> (May 2026).
</p>

---

## What is this?

A working AI system that ingests multiple business documents (invoices,
contracts, delivery notes, purchase orders, financial reports) and:

- **Extracts structured data** with anti-hallucination layers (5+1 stack)
- **Detects risks** via 14 deterministic domain rules + LLM ensemble
- **Cross-references documents** (three-way matching for audits, M&A DD)
- **Answers questions** via 5-tool agentic chat with source citations
- **Generates audit-ready reports** (DOCX export, JSON API)

This is **not "just another RAG"** — it is a multi-agent orchestration of
specialist nodes (audit / legal / compliance / financial) over a deterministic
+ LLM ensemble, with explicit anti-hallucination layers.

## Stack

| Layer | Technology |
|-------|------------|
| Orchestration | **LangGraph 0.6** (4 graphs, 6 subgraphs, async-first, AsyncSqliteSaver) |
| LLM | **Qwen 2.5 14B Instruct** via vLLM on **AMD Instinct MI300X** |
| Embedding | **BAAI/bge-m3** (multilingual, 1024 dim, sentence-transformers) |
| Vector store | **ChromaDB + BM25** hybrid (Reciprocal Rank Fusion) |
| UI | **Streamlit** (5 tabs) — deployable as a **Hugging Face Space** |
| Testing | pytest + Playwright |

## Architecture

```
                    ┌─────────────────────────────────┐
                    │    Streamlit UI (5 tabs)        │
                    └────────────┬────────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
┌───────▼──────┐        ┌────────▼────────┐       ┌──────▼──────┐
│ pipeline     │        │  chat_graph     │       │  dd_graph   │
│ _graph       │        │  (5 tools, 17   │       │  (multi-    │
│ (6 subgraphs)│        │  rule prompt)   │       │  agent      │
└───────┬──────┘        └─────────────────┘       │  super-     │
        │                                          │  visor)     │
        │  ┌─────────────────────────┐             └─────────────┘
        ├──▶ ingest_subgraph         │
        ├──▶ classify (per-doc)      │
        ├──▶ extract_subgraph        │
        ├──▶ rag_index_subgraph      │
        ├──▶ compare_node (3-way)    │
        └──▶ risk_subgraph           │
             ├─ basic risk           │
             ├─ 14 domain checks     │
             ├─ LLM risk + 3 filters │
             ├─ plausibility         │
             └─ duplicate (ISA 240)  │
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full architecture.

## Quick start

### 1. Local dev (Ollama or dummy mode)

```bash
git clone https://github.com/<YOUR_GH_USER>/document-intelligence-agentic-langgraph-amd
cd document-intelligence-agentic-langgraph-amd
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set LLM_PROFILE=dummy (no LLM) or LLM_PROFILE=ollama (Qwen 7B local)

streamlit run app/main.py
```

### 2. Production (Qwen on AMD MI300X via vLLM)

```bash
# On the AMD Developer Cloud MI300X instance:
docker run --rm --device=/dev/kfd --device=/dev/dri --group-add video \
    --ipc=host --shm-size 16g \
    -p 8000:8000 \
    -e VLLM_MODEL=Qwen/Qwen2.5-14B-Instruct \
    rocm/vllm:latest \
    sh -c 'vllm serve $VLLM_MODEL --host 0.0.0.0 --port 8000 \
        --tensor-parallel-size 1 --max-model-len 32768'

# On your machine (.env):
LLM_PROFILE=vllm
VLLM_BASE_URL=http://<mi300x-public-ip>:8000/v1
VLLM_MODEL=Qwen/Qwen2.5-14B-Instruct

streamlit run app/main.py
```

See [docs/qwen-vllm-deployment.md](docs/qwen-vllm-deployment.md) for the full
walkthrough including cost monitoring and a Plan B (Ollama fallback).

### 3. Hugging Face Space deploy

See [docs/hf-space-deployment.md](docs/hf-space-deployment.md).

## Demo packages

Three pre-built demo packages bundled in `test_data/`:

- **Audit Demo** — 3 invoices from the same supplier; the March one is 50%
  pricier (over-billing pattern detected by the package-level analyzer).
- **DD Demo** — NDA + service agreement + amendment in an acquisition
  scenario (change-of-control + auto-renewal red flags).
- **Compliance Demo** — 2 contracts; one is missing the GDPR Article 28 clause.

Click the corresponding button on the **Upload** tab.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — architecture overview (English)
- [docs/qwen-vllm-deployment.md](docs/qwen-vllm-deployment.md) — Qwen on AMD MI300X (English)
- [docs/hf-space-deployment.md](docs/hf-space-deployment.md) — Hugging Face Space deploy (English)
- [docs/LANGGRAPH_ONBOARDING.md](docs/LANGGRAPH_ONBOARDING.md) — onboarding for contributors (English)
- [CLAUDE.md](CLAUDE.md) — project-level Claude Code instructions
- [NOTICE.md](NOTICE.md) — author intent (non-binding)
- `docs/Teljes-rendszer-attekintes-langgraph_HU.md` — legacy Hungarian system overview (reference)
- `docs/MUKODESI_LEIRAS_HU.md` — legacy Hungarian operations manual (reference)

## Built by

**Team CsimpiCsirkek** for the AMD Developer Hackathon × lablab.ai (2026):

- Nándorfi Vince
- Vitai Tamás
- Murcsik Gábor

## License

**MIT** — see [LICENSE](LICENSE).
