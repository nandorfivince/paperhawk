# Architecture

LangGraph-native Document Intelligence platform. This document goes beyond
the README — it covers design decisions, the subgraph hierarchy, state
design, and the anti-hallucination stack.

## 1. High-level architecture

### 4 compiled LangGraph artifacts

The system is organized around four graphs sharing a common `AsyncSqliteSaver`
checkpointer:

| # | Graph | Entry point | When |
|---|-------|-------------|------|
| 1 | `pipeline_graph` | `app.run_pipeline(files)` | on upload |
| 2 | `chat_graph` | `app.ask(question)` | chat tab |
| 3 | `dd_graph` | `app.dd_report(thread_id)` | DD tab button |
| 4 | `package_insights_graph` | `app.package_insights(thread_id, pkg_type)` | demo button |

Chat tools read from the persisted pipeline state — they do not re-read
files. They access the in-memory `ChatToolContext`, which holds the
HybridStore and a documents snapshot.

### Pipeline graph topology

```
START
  → start_timer
  → dispatch_ingest          (Send API: per-doc fan-out)
  → ingest_per_doc           (PDF/DOCX/PNG/TXT loader subgraph)
  → ingest_join              (fan-in)
  → dispatch_classify        (Send API)
  → classify_per_doc         (regex/keyword classifier in dummy mode;
                              vision-aware in vLLM mode)
  → classify_join
  → dispatch_extract         (Send API)
  → extract_per_doc          (regex extractor in dummy mode +
                              flatten_universal; structured LLM in vLLM mode)
  → extract_join
  → quote_validator          (anti-hallucination layer #7)
  → dispatch_rag_index       (Send API)
  → rag_index_per_doc        (chunker + batched embed + Chroma+BM25 upsert)
  → rag_join
  → compare_node             (three-way matching, sync)
  → risk_subgraph            (basic + 14 domain × Send + plausibility +
                              LLM ensemble + duplicate)
  → finish_timer
  → report_node              (10-section JSON structure)
  → END
```

The per-doc Send fan-out yields a 5–8× speedup in a CPU-bound environment.

### Risk subgraph topology

```
risk_subgraph (input: PipelineState):
  → basic_risk_dispatch         (Send: per-doc basic risk)
  → basic_risk / noop_basic
  → domain_dispatch_node        (Send: per-doc × per-applicable-check, ~30 parallel)
  → apply_domain_check
  → [if llm provided] llm_risk_dispatch  (Send: per-doc LLM risk + 3-filter chain)
  → llm_risk_per_doc / noop_llm
  → plausibility_dispatch       (Send: per-doc plausibility)
  → plausibility / noop_plaus
  → evidence_score_node         (per-doc info)
  → duplicate_detector_node     (package-level, sync, ISA 240)
END
```

The full anti-hallucination 5+1 layer chain runs inside `llm_risk_per_doc`:
`llm_risk → filter_llm_risks → drop_business_normal → drop_repeats`.

### DD multi-agent supervisor graph

```
dd_graph:
  START
  → contract_filter_node      (keep only contract-type docs)
  → per_contract_summary_node (Python-deterministic per-contract DDContractSummary)
  → supervisor_node           (LLM router or heuristic; Command(goto=...))
        ├─ → audit_specialist     (pricing anomalies, overcharging)
        ├─ → legal_specialist     (red flags, change-of-control, non-compete)
        ├─ → compliance_specialist (GDPR, AML, data protection)
        └─ → financial_specialist (monthly obligations, expirations)
  ↺ (loops back to supervisor up to dd_supervisor_max_iterations)
  → dd_synthesizer            (one LLM call: executive_summary +
                               top_red_flags + per-contract risk_level rating)
  END
```

### Package insights graph

A simple 1-LLM-call graph: ingests the full document package and produces
cross-doc findings using a perspective-driven prompt
(`audit | dd | compliance | general`).

## 2. State design

### `PipelineState` (TypedDict)

Read-mostly fields with **reducer-driven Send fan-in**:

- `files: list[tuple[str, bytes]]` — raw upload
- `documents: Annotated[list[ProcessedDocument], merge_doc_results]` —
  per-doc field-level merge keyed by `file_name`
- `risks: Annotated[list[Risk], merge_risks]` — dedup by description
- `comparison: ComparisonReport | None`
- `report: dict`
- `package_insights: PackageInsights | None`
- `dd_report: DDPortfolioReport | None`
- `started_at`, `finished_at`, `processing_seconds`
- `progress_events: Annotated[list[str], add]` — Streamlit progress feed

### `Risk` (Pydantic)

The single risk type used everywhere:

- `description: str`
- `severity: str` (`"high" | "medium" | "low" | "info"`)
- `rationale: str`
- `kind: str` (`"validation" | "domain_rule" | "plausibility" | "llm_analysis" | "cross_check"`)
- `regulation: str | None` (e.g. `"HU VAT Act §169"`, `"ISA 240"`, `"GDPR Article 28"`)
- `affected_document: str | None`
- `source_check_id: str | None`

## 3. Anti-hallucination stack (5+1 layers)

1. **`temperature=0`** — every LLM call is deterministic-ish.
2. **`_quotes` schema field** — verbatim source citations.
3. **`_confidence` schema field** — per-field reliability (high|medium|low).
4. **`validate_plausibility()`** — Python deterministic plausibility checks
   (negative VAT, non-standard rates, future dates, etc.).
5. **3-filter LLM risk pipeline** —
   `filter_llm_risks` (formal: ≥5 words, ≥2 domain terms, ≥1 concrete fact)
   → `drop_business_normal_risks` (semantic: cross-check vs extracted_data,
   6 known false-positive patterns)
   → `drop_repeats_of_basic` (textual dedup vs basic risks, 70% threshold).
6. **Quote validator** — final cross-check that every `_quotes` entry
   actually appears in the source `full_text` (whitespace + diacritic +
   case normalized). If invalid, downgrades confidence.

## 4. Domain checks (14 deterministic rules)

| # | check_id | Regulation | HU-specific? | Applies to |
|---|----------|-----------|--------------|------------|
| 01 | `check_01_invoice_mandatory` | HU VAT Act §169 | yes | invoice |
| 02 | `check_02_tax_cdv` | HU Tax Procedure Act §22 mod-11 | yes | invoice + contract + ... |
| 03 | `check_03_contract_completeness` | Universal contract completeness | no | contract |
| 04 | `check_04_proportionality` | Universal contract proportionality (>31.7%) | no | contract |
| 05 | `check_05_rounded_amounts` | ISA 240 (Journal of Accountancy 2018) | no | invoice |
| 06 | `check_06_evidence_score` | ISA 500 | no | (separate entry, info-only) |
| 07 | `check_07_materiality` | ISA 320 | no | invoice + contract + financial_report |
| 08 | `check_08_gdpr_28` | GDPR Article 28 | no (EU) | contract |
| 09 | `check_09_dd_red_flags` | M&A DD best practice | no | contract |
| 10 | `check_10_incoterms` | Incoterms 2020 | no | contract |
| 11 | `check_11_ifrs_har` | IFRS / national GAAP comparison | no | financial_report |
| 12 | `check_12_duplicate_invoice` | ISA 240 (duplicate invoice) | no | (separate entry, package-level) |
| 13 | `check_13_aml_sanctions` | AML / Sanctions screening | no | invoice + contract + ... |
| 14 | `check_14_contract_dates` | Contract date best practice | no | contract |

The dispatch in `domain_dispatch_node` skips `check_06` and `check_12` (they
have separate entry points) and filters `is_hu_specific=True` out for non-HU
documents.

## 5. Provider system

Three providers via `configurable_alternatives`:

- **`vllm`** — `ChatOpenAI` with `base_url=VLLM_BASE_URL` pointing at the
  AMD MI300X vLLM endpoint. Production default.
- **`ollama`** — `ChatOllama` with a local Ollama daemon (Qwen 2.5 7B
  Instruct). Development fallback.
- **`dummy`** — `DummyChatModel` (deterministic stub, no network).
  CI / eval / load.

Provider selection is **runtime-switchable** without restart:

```python
graph.invoke(state, config={"configurable": {"llm_profile": "dummy"}})
```

## 6. Embedding

`BAAI/bge-m3` (2.27 GB, 1024 dim, multilingual) by default.
Sentence-transformers loads it on first call via `@lru_cache`.
Pre-downloaded at Docker build time so runtime has no network call.

## 7. Hybrid retrieval (Chroma + BM25)

`store/hybrid_store.py` runs vector search and BM25 in parallel and merges
with Reciprocal Rank Fusion (RRF). The chunker uses natural break points
(paragraph + sentence boundaries), tuned to ~15K-char chunks with 500-char
overlap.

## 8. Async-first runtime

LangGraph 0.6 is async-first. The Streamlit app runs the entire async layer
on a long-lived background event loop (`app/async_runtime.py`'s `AsyncRuntime`
singleton). This keeps the ChromaDB connection, the Anthropic / OpenAI HTTP
session, and the `AsyncSqliteSaver` SQLite pool persistent across user
interactions — they do not rebuild per request.

## 9. Multilingual support

The codebase is English-first but multilingual-tolerant:

- The classifier matches HU/EN/DE keyword patterns.
- Risk filters tolerate HU/DE business terms.
- The OCR layer keeps `eng + hun + deu` as Tesseract languages.
- Demo data may include mixed-language documents.

The output (UI, exec summary, DOCX report) is **always English**.
