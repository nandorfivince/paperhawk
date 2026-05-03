# CLAUDE.md — paperhawk

Project-level instructions for Claude Code working in this repository. Any
session that starts in this folder reads this file automatically.

**Last updated:** 2026-05-03

---

## 1. Project overview

A LangGraph-native, multi-agent Document Intelligence platform built for the
**AMD Developer Hackathon × lablab.ai** (May 2026). MIT-licensed, English-only
codebase, designed to run on **AMD Instinct MI300X** GPUs via the vLLM runtime
serving **Qwen 2.5 Instruct** open-source models.

The system processes business document packages (invoices, contracts, delivery
notes, purchase orders, financial reports) end-to-end:

1. **Ingest** — PDF / DOCX / image with vision-first scanned fallback
2. **Classify** — 6-way doc-type classifier (LLM with structured output)
3. **Extract** — typed Pydantic schema extraction with anti-hallucination
4. **Cross-reference** — three-way matching (invoice + delivery + PO)
5. **Risk analysis** — basic + 14 domain rules + LLM ensemble + 3 filters
6. **Report** — DOCX export, JSON API, executive summary

The chat layer is a 5-tool agentic ReAct loop with explicit `[Source: filename]`
citations and an anti-hallucination validator.

---

## 2. Workflow rules

### Language

- **English everywhere** — code, comments, docstrings, prompts, UI, error
  messages, log lines.
- **Multilingual fallback** — for legacy interop and the multilingual demo:
  some loaders, classifiers, and regex filters accept HU/DE input. EN is
  always the primary path.
- Two HU reference documents are kept under `docs/` with `_HU.md` suffix
  (`Teljes-rendszer-attekintes-langgraph_HU.md`, `MUKODESI_LEIRAS_HU.md`).
  These are read-only references; do not edit.

### License + IP

- **MIT licensed** — see `LICENSE`.
- `NOTICE.md` is a non-binding author request (no legal force).
- Never paste proprietary code from outside this repo.

### Provider

- The default chat provider is `vllm` (Qwen 2.5 14B Instruct on AMD MI300X
  through the OpenAI-compatible vLLM endpoint).
- `ollama` is a local dev fallback (Qwen 2.5 7B Instruct on a laptop GPU/CPU).
- `dummy` is the deterministic CI / eval / smoke provider (no network, no LLM).
- Never re-introduce a Claude / Anthropic provider here — that path is
  out of scope for the AMD edition.

### Git

- The AI **NEVER** runs git operations on `main` (no commit, no push, no
  cherry-pick, no merge). The user runs all `main`-branch git operations.
- The AI MAY commit on non-`main` feature branches when explicitly asked.
- The AI **NEVER** pushes — push is the user's task only.

### Build hygiene

- Do not commit `.env`, `chroma_db/`, `data/checkpoints.sqlite`, `__pycache__/`.
- Magyar / English commit messages are both fine; English preferred for the
  public history of an MIT repo.

### Anti-hallucination is sacred

- The 5+1 layers (`temperature=0`, `_quotes`, `_confidence`, plausibility
  filters, LLM-risk 3 filters, quote validator) are not optional. Every
  LLM-generated piece of data is cross-checked.
- Source citations in the chat use the canonical `[Source: filename]` format
  (validator enforces this).

---

## 3. Repo layout

```
paperhawk/
├── app/                   # Streamlit UI (5 tabs) + async runtime
├── config.py              # Pydantic Settings (env-bound)
├── domain_checks/         # 14 deterministic rules + base + registry
├── eval/                  # Eval harness (questions + run_eval)
├── graph/                 # 4 compiled graphs (pipeline / chat / dd /
│                          # package_insights) + 6 states + checkpointer
├── ingest/                # PDF / DOCX / image / OCR / tables / txt
├── infra/vllm/            # AMD MI300X deployment (Dockerfile + serve.sh + README)
├── load/                  # Load benchmarks
├── nodes/                 # Per-stage node functions:
│   ├── chat/              #   chat agent + 5 tools
│   ├── dd/                #   DD specialists + supervisor + synthesizer
│   ├── extract/           #   extract + dummy + quote validator
│   ├── ingest/            #   ingest helpers
│   ├── pipeline/          #   classify / compare / duplicate / report / docx
│   └── risk/              #   basic / domain dispatch / LLM risk + 3 filters
├── providers/             # vLLM / Ollama / Dummy LLM providers + embeddings
├── schemas/               # 6 JSON schemas + pydantic_models + flatten_universal
├── store/                 # ChromaDB + BM25 hybrid + chunking
├── subgraphs/             # 6 reusable subgraphs (Send API parallelism)
├── tests/                 # unit + integration + e2e_api + e2e_screenshot
├── tools/                 # 5 chat tools + ChatToolContext
├── utils/                 # dates + numbers + docx_export
└── validation/            # anti-halluc layers (5+1)
```

---

## 4. Hot files

When fixing bugs or adding features, these are the most-edited files:

- `graph/states/pipeline_state.py` — `Risk`, `Classification`, `ExtractedData`,
  `merge_risks`, `merge_doc_results` reducers.
- `domain_checks/__init__.py` — the 14-check registry.
- `domain_checks/check_*_*.py` — individual deterministic rules.
- `nodes/risk/_prompts.py` — `RISK_SYSTEM_PROMPT` (anti-halluc 9+6+4 examples).
- `nodes/chat/_prompts.py` — `AGENTIC_SYSTEM_PROMPT` (17 rules).
- `validation/llm_risk_filters.py` — 3-filter chain.
- `app/main.py` — Streamlit UI (5 tabs).

---

## 5. Testing

```bash
# Fast: unit + integration (dummy LLM)
LLM_PROFILE=dummy pytest tests/unit tests/integration -x --tb=short

# Slow: end-to-end with real LLM
LLM_PROFILE=vllm pytest tests/e2e_api -m e2e -x --tb=short

# UI Playwright (real LLM, slow)
LLM_PROFILE=vllm pytest tests/e2e_screenshot -x --tb=short
```

`LLM_PROFILE=dummy` works without any external service. `LLM_PROFILE=vllm`
requires `VLLM_BASE_URL` to point at a running vLLM endpoint.

---

## 6. Deploy targets

- **Hugging Face Space** — Streamlit Space under
  `huggingface.co/spaces/lablab-ai-amd-developer-hackathon/<your-space>`.
  See `docs/hf-space-deployment.md`.
- **AMD Developer Cloud MI300X** — vLLM serving Qwen 2.5 14B (or 32B).
  See `docs/qwen-vllm-deployment.md` and `infra/vllm/README.md`.

---

## 7. Pitch positioning

When writing project descriptions, the README, video, or social posts:

- **Beyond simple RAG** — multi-agent platform with 14 deterministic checks
  + an LLM ensemble. The 5-tool chat is *agentic*, not retrieval-only.
- **Track 1** (AI Agents & Agentic Workflows) is the target track.
- **Cross-track**: Build in Public is in scope (AMD GPU prize).
- **HF Special Prize** is in scope (Reachy Mini robot — like-vote driven).

---

## 8. The Glossary (HU → EN field names)

The full per-field rename map is in
`pwc-ai-verseny/document-intelligence-agentic-langgraph-amd/ATIRASI_TERV.md`
sections **32 (field names) and 33 (severity literals)**. Keep that file
open when editing extraction schemas, domain checks, or anything that
touches the `Risk` Pydantic.

---

## 9. Common pitfalls

- **Severity literals**: always `"high" | "medium" | "low" | "info"` —
  never `"magas" | "kozepes" | "alacsony"`. Many `_normalize_severity()`
  helpers map HU → EN if legacy data sneaks in, but new code emits EN.
- **Risk fields**: `description`, `severity`, `rationale`, `kind`,
  `regulation`, `affected_document`, `source_check_id`. NOT
  `leiras / sulyossag / indoklas / tipus / jogszabaly / erinto_dokumentum / forras_check_id`.
- **Doc types**: `"invoice" | "delivery_note" | "purchase_order" | "contract" | "financial_report" | "other"`.
- **`_quotes` alias** (not `_idezetek`) — both in JSON schemas and Pydantic models.
- **Multilingual fallback**: read-only in classifiers and regex filters;
  never emit HU in new code.
