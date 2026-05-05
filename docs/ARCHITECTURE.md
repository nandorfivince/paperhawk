# PaperHawk Architecture

How PaperHawk is built and why each piece is where it is. This document explains the multi-graph LangGraph orchestration, the 14 deterministic domain checks, the 6-layer anti-hallucination stack, and the multi-agent DD assistant.

---

## High-level architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          USER (Streamlit 5-tab UI)                       │
│   Upload  │  Results  │  Chat  │  DD Assistant  │  Report                │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │
            ┌────────────────────┼────────────────────────┐
            │                    │                        │
            ▼                    ▼                        ▼
   ┌──────────────────┐ ┌──────────────────┐  ┌─────────────────────────┐
   │  pipeline_graph  │ │   chat_graph     │  │    dd_graph             │
   │                  │ │                  │  │                         │
   │ Ingest →         │ │ Intent classify  │  │ Contract filter →       │
   │ Classify →       │ │ → Plan →         │  │ Per-contract summary →  │
   │ Extract →        │ │ Agent (5 tools)  │  │ Multi-agent specialists │
   │ Compare →        │ │ → Synthesizer →  │  │ (audit/legal/compliance │
   │ Risk →           │ │ Validator        │  │  /financial) →          │
   │ Report           │ │ ([Source: …])    │  │ Supervisor → Synthesizer│
   └──────────────────┘ └──────────────────┘  └─────────────────────────┘
            │                                        │
            └─────────────┬──────────────────────────┘
                          ▼
                ┌──────────────────────────┐
                │  package_insights_graph  │
                │                          │
                │  Cross-document analysis │
                │  (price-drift, dupes,    │
                │   three-way matching)    │
                └──────────────────────────┘
                          │
                          ▼
                ┌──────────────────────────┐
                │    Provider abstraction  │
                │ (configurable_alternatives)
                │                          │
                │ vLLM ←→ Ollama ←→ Dummy  │
                └──────────────────────────┘
                          │
                          ▼
                ┌──────────────────────────┐
                │  AMD MI300X (vLLM)       │
                │  Qwen 2.5 14B Instruct   │
                │  192 GB HBM3, ROCm 7.0   │
                └──────────────────────────┘
```

---

## Compiled graphs (4)

Every entry-point in the system is a separately compiled LangGraph artifact with its own typed state and `AsyncSqliteSaver` checkpointer:

### 1. `pipeline_graph` — the document processing pipeline

The 6-step end-to-end flow when the user uploads a package:

1. **Ingest** — PDF (PyMuPDF + pdfplumber for table extraction), DOCX (native), images (vision-first via the LLM), with Tesseract OCR fallback for scanned PDFs (EN/HU/DE)
2. **Classify** — 6-way doc-type classifier with structured output (`invoice`, `delivery_note`, `purchase_order`, `contract`, `financial_report`, `other`); ISA 500 evidence-quality score
3. **Extract** — per doc-type Pydantic v2 schema with `_quotes` and `_confidence` fields; universal fallback schema for unknown types
4. **Compare** — three-way matching subgraph (invoice + delivery note + PO), duplicate-invoice detection (ISA 240)
5. **Risk** — basic plausibility + 14 domain checks (Send-API parallel fan-out) + LLM risk ensemble + 3-stage filter chain
6. **Report** — DOCX export, JSON output, Streamlit UI rendering

State: `PipelineState` (Pydantic), with reducers for risk lists and per-document results.

### 2. `chat_graph` — the agentic chat

5-tool ReAct agent with strict citation enforcement:

- **Tools**: `list_documents`, `get_extraction`, `search_documents` (hybrid Chroma + BM25 with Reciprocal Rank Fusion), `compare_documents`, `validate_document`
- **Prompt**: 17-rule system prompt enforcing `[Source: filename.pdf]` format
- **Validator node**: post-processor that drops any answer without citations
- **Intent classifier**: routes to direct-answer vs tool-use paths to keep latency low for casual queries

State: `ChatState` with message history, retrieved chunks, and citation list.

### 3. `dd_graph` — the multi-agent DD assistant

For M&A due-diligence packages:

- **Contract filter** — selects only contract-type documents from the package
- **Per-contract summary** — extracts each contract's key terms (parties, term, value, change-of-control, non-compete, auto-renewal)
- **4 specialist agents** (run in parallel via Send-API):
  - `audit_specialist` — material misstatement risk, ISA 240 fraud indicators
  - `legal_specialist` — change-of-control, non-compete, automatic-renewal red flags
  - `compliance_specialist` — GDPR Art. 28 sub-processor language, AML counterparty checks
  - `financial_specialist` — Ptk. 6:98 disproportionate penalty clauses, materiality thresholds
- **Supervisor** — coordinates specialists, drops business-normal noise
- **Synthesizer** — writes 3-paragraph executive summary

State: `DDState` with contract list, per-contract summaries, specialist findings, executive summary.

### 4. `package_insights_graph` — cross-document analysis

Package-level analyzers that don't fit into the per-document pipeline:

- **Pricing-drift detector** — flags > 30% price changes for the same line item across invoices in a package (caught the 57.5% drift in our live demo)
- **Duplicate-invoice detector** — exact + near-match (date within 13 days, amount within 1%)
- **Counterparty consistency** — same supplier name spelled differently across documents

State: `PackageState` with per-document extractions and aggregated findings.

---

## Subgraphs (6)

Reusable LangGraph subgraphs imported by the main graphs:

| Subgraph | Purpose |
|---|---|
| `extract_subgraph` | Per-document extraction with quote validator |
| `ingest_subgraph` | PDF/DOCX/image loading with OCR fallback |
| `llm_risk_subgraph` | LLM risk generation with structured output |
| `rag_index_subgraph` | Chunking, embedding, ChromaDB indexing |
| `rag_query_subgraph` | Hybrid Chroma + BM25 retrieval with RRF |
| `risk_subgraph` | Domain check fan-out + LLM risk + 3-stage filters |

---

## 14 deterministic domain checks

The check registry (`domain_checks/__init__.py`) is the heart of PaperHawk's auditor-grade output. Every check is a Python `Protocol` implementation, not an LLM prompt — they cannot hallucinate, can be unit-tested, and produce defensible findings with explicit regulation sources.

### A-tier (essential)

1. **Mandatory invoice elements** (HU VAT Act §169) — 18 required elements per invoice
2. **Tax-ID checksum** (Art. 22 §) — mod-11 Hungarian tax-ID validation
3. **Contract completeness** (Ptk. Book 6) — termination, governing law, penalty, confidentiality clauses
4. **Disproportionality** (Ptk. 6:98) — penalty clause > 31.7% of contract value flagged HIGH
5. **Rounded amounts** (ISA 240) — > 14.7% rounded amounts flagged suspicious, > 24.3% flagged HIGH
6. **Evidence hierarchy** (ISA 500) — document-type reliability score (8/10 invoice, 7/10 contract)

### B-tier (supplementary)

7. **Materiality** (ISA 320) — 1.93% of document value as info-level threshold
8. **GDPR Article 28** — 10 mandatory sub-processor language elements + PII detection
9. **DD red flags** (M&A) — change-of-control, non-compete, automatic-renewal triggers

### C-tier (informational)

10. **Incoterms 2020** — 11 incoterm rules detected via regex word-boundaries
11. **IFRS/HAR anomaly** — goodwill amortization flag, operational lease in IFRS context
12. **Duplicate invoice** (ISA 240) — exact + near-match with 13-day date filter
13. **AML sanctions** (Pmt.) — static EU/OFAC snapshot with fuzzy name match
14. **Contract dates** — start-end consistency, expiry detection

**Jurisdiction-aware**: Hungarian-specific rules (HU VAT Act, Ptk., Art.) apply only to Hungarian documents. Universal rules (ISA, GDPR, Incoterms, AML) apply everywhere.

---

## 6-layer anti-hallucination stack

The system is designed so the LLM **cannot** lie about a document and have the lie pass through.

| Layer | What it does |
|---|---|
| 1. `temperature=0` | Deterministic outputs every run |
| 2. Source quote requirement | Every extraction must include a verbatim quote from the source PDF in `_quotes` |
| 3. Confidence scoring | high / medium / low per extracted field, surfaced to the user |
| 4. Plausibility validators | Deterministic Python checks for math, dates, totals, item-level VAT, currency normalization |
| 5. 3-stage LLM-risk filter chain | Drops business-normal noise, drops repeats of basic deterministic checks, drops contradictions |
| 6. Quote validator | Text-search the source PDF for the claimed quote; downgrade confidence if not found verbatim, drop entirely if obviously fabricated |

In our live audit demo, layer 6 caught **4 of 6** hallucinated citations from Qwen 2.5 14B and downgraded them to `low` confidence.

The `validation/` package is one of the most-edited folders in the repo precisely because we treat anti-hallucination as a first-class concern, not a guardrail layer slapped on top.

---

## Provider abstraction

`configurable_alternatives` lets us swap LLM backends with a single env var:

| `LLM_PROFILE` | Backend | Use case |
|---|---|---|
| `vllm` | vLLM REST endpoint (OpenAI-compatible) | Production on AMD MI300X |
| `ollama` | Local Ollama at `localhost:11434` | Dev on consumer GPU |
| `dummy` | Deterministic stub | CI tests, smoke tests, judge quick-demo |

The application code never imports an LLM SDK directly — all calls go through `providers/` factory functions with `configurable_alternatives`. Switching from Anthropic Claude (our original dev target) to Qwen on vLLM required **zero application code changes** — only env vars.

---

## Embedding + retrieval

- **Model**: BAAI/bge-m3 (1024-dim, multilingual EN/HU/DE/FR via sentence-transformers)
- **Storage**: ChromaDB persistent (per-session) + BM25 in-memory keyword index
- **Hybrid retrieval**: Reciprocal Rank Fusion of Chroma top-K and BM25 top-K
- **Chunking**: Natural-boundary chunking (paragraph-aware, ~500 tokens with overlap)

The embedding model loads once at app startup (~2.3 GB to RAM/VRAM). On first run it downloads from Hugging Face Hub to `~/.cache/huggingface/`.

---

## State persistence

- **Per-session**: Streamlit `session_state` for UI state (uploaded files, current package)
- **Per-graph**: `AsyncSqliteSaver` checkpointer at `data/checkpoints.sqlite` for LangGraph state
- **Vector store**: ChromaDB at `chroma_db/` (gitignored)

Restarting the app loads the last checkpoint, so chat history and extraction results survive a restart.

---

## Streamlit UI (5 tabs)

1. **Upload** — drag-and-drop (PDF, DOCX, PNG, JPG, TXT), 200 MB per file, plus 3 pre-bundled demo packages
2. **Results** — classification confidence, extracted data, risks per document, package-level cross-doc analysis
3. **Chat** — agentic chat with `[Source: filename.pdf]` citations
4. **DD Assistant** — for M&A packages: per-contract summaries + 4 specialist findings + executive summary + downloadable DOCX
5. **Report** — JSON output + DOCX export

The async runtime uses a long-lived background event loop (`app/async_runtime.py`) so the UI stays responsive during multi-minute pipeline runs.

---

## Cross-references

- [`docs/AMD_DEPLOYMENT.md`](AMD_DEPLOYMENT.md) — how the production vLLM endpoint runs on AMD MI300X
- [`docs/HUGGINGFACE_DEPLOYMENT.md`](HUGGINGFACE_DEPLOYMENT.md) — how the Streamlit app deploys as a public HF Space
- [`docs/SUBMISSION.md`](SUBMISSION.md) — full hackathon submission brief with TAM/SAM, competitor positioning, live deployment validation
