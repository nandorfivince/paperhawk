# PaperHawk — Hackathon Submission Brief

> One-pager for the **AMD Developer Hackathon × lablab.ai** (May 2026) submission form.
> Every section below is ready to paste directly into the lablab.ai project page.

---

## Project Title

**PaperHawk**

---

## Short Description

> Multi-agent document intelligence that catches what RAG misses. 14 deterministic domain checks, 5+1 anti-hallucination layers, and a 5-tool agentic chat — running Qwen 2.5 on AMD Instinct MI300X via vLLM. Open source, MIT licensed.

*(247 characters)*

---

## Long Description

### The Problem

RAG retrieves passages. Audit finds inconsistencies. Today's RAG chatbots can't do the second.

When someone opens a folder of 25 invoices, three contracts, two purchase orders, and a financial report, they don't ask a chatbot to summarize the contract. They ask: *"Does the supplier in Invoice #7 match the vendor in PO #3? Is the VAT rate consistent across the package? Is there a hidden change-of-control clause? Is the math on the gross total correct? Are any of these counterparties on the EU/OFAC sanctions list?"*

These are not retrieval questions. They are **reasoning, validation, and cross-reference** questions over multiple typed documents. A standard chunk-embed-retrieve-generate pipeline cannot answer them, because the question is not contained in any single chunk. It lives in the relationship between documents.

PaperHawk is built specifically for this gap.

### What We Built

PaperHawk is a LangGraph 0.6-native system with **4 compiled graphs** (pipeline, chat, DD assistant, package insights) wired together with **Send-API parallelism**, an `AsyncSqliteSaver` checkpointer, and a `configurable_alternatives` provider that swaps cleanly between vLLM (production), Ollama (local dev), and a deterministic dummy (CI). It is not a single-agent retrieval pipeline.

Concretely:

- **6 reusable subgraphs** for ingest, classification, extraction, risk dispatch, LLM risk ensemble, and chat tool routing
- **14 deterministic domain checks** wired into a registry — ISA 240/500/320 (audit standards), GDPR Article 28, Incoterms 2020, AML sanctions, tax-ID validation, contract completeness, materiality thresholds, and more. Every check is a Python `Protocol` implementation, not an LLM prompt.
- **5+1 anti-hallucination layers**: `temperature=0`, a `_quotes` field for verbatim source citation, `_confidence` per extracted field, plausibility validators, a 3-layer LLM-risk filter chain, and a quote validator that drops any LLM output whose claimed source quote isn't found in the document.
- **5-tool agentic chat** (`list_documents`, `get_extraction`, `search_documents`, `compare_documents`, `validate_document`) with strict `[Source: filename.pdf]` citations validated by a post-processor — answers without provenance never reach the user.
- **Multi-agent DD assistant**: 4 specialist agents (audit / legal / compliance / financial) coordinated by a supervisor and a synthesizer, in the spirit of the LangGraph supervisor cookbook but production-shaped.
- **Streamlit 5-tab UI**: Upload, Results, Chat, DD Assistant, Report — drivable in 30 seconds with three pre-bundled demo packages.

The codebase ships with **61 tests passing in CI** without any LLM (the deterministic dummy provider), is MIT licensed, and is English-first with a multilingual fallback path for EN/HU/DE inputs.

### Why AMD Instinct MI300X

The MI300X gives us **192 GB of HBM3 memory** in a single accelerator — enough headroom to host Qwen 2.5 14B Instruct in BF16 with comfortable KV-cache space for our long agentic conversations. The DD supervisor plus four specialists in one session easily exceeds 32k tokens of context, and the MI300X handles it without paging.

vLLM's continuous batching on ROCm lets the Streamlit UI fire concurrent requests during a multi-document upload without queueing artifacts. The FP8 / BF16 paths supported by the MI300X memory bandwidth open a clean upgrade route to Qwen 2.5 32B for finals night.

We're using the AMD Developer Cloud — `infra/vllm/Dockerfile` and `infra/vllm/serve.sh` are committed in the repo and start vLLM with `--api-key`, `--max-model-len 32768`, and a configurable model tag. The whole inference stack is containerized; nothing is hand-rolled on the GPU node.

### Why Qwen 2.5 Instruct

Three reasons.

First, **strong tool calling**. Qwen 2.5 14B handles our 5-tool chat router reliably; tool-routing accuracy in our integration tests is on par with the proprietary reference model we used in early development. The tool-call JSON is well-formed, parameters are typed correctly, and unnecessary tool calls are rare.

Second, **structured output that holds**. `with_structured_output` returns valid Pydantic v2 JSON every time in our extraction subgraph, including the nested `_quotes` and `_confidence` fields. This is where many smaller open-source models fail under load — Qwen 2.5 doesn't.

Third, **multilingual fluency**. Our pipeline often reads Hungarian, German, and English documents in the same package, and Qwen handles cross-lingual extraction without dropping accuracy. We don't fine-tune; we pull `Qwen/Qwen2.5-14B-Instruct` from Hugging Face directly into the vLLM container — clean, reproducible, and rerunnable by anyone.

### The Pipeline (5-Step End-to-End)

1. **Ingest** — PDF, DOCX, and image inputs go through three loaders. Scanned PDFs hit a vision-first fallback (the LLM reads the rendered page directly); native PDFs use PyMuPDF + pdfplumber for table-aware extraction; DOCX is parsed natively.
2. **Classify** — A 6-way doc-type classifier (`invoice`, `delivery_note`, `purchase_order`, `contract`, `financial_report`, `other`) with structured output, calibrated for ISA 500 evidence-quality scoring.
3. **Extract** — Per doc-type Pydantic schema, with a universal extraction subgraph as a fallback for unknown types. Every extracted field carries its own `_quotes` and `_confidence` — anti-hallucination is built into the type system, not a post-hoc check.
4. **Cross-reference** — Three-way matching (invoice + delivery note + purchase order) for audit packages; multi-agent synthesis for DD packages; package-level analyzers for duplicate-invoice detection (ISA 240) and pricing anomalies.
5. **Risk + Report** — Plausibility checks + 14 domain checks (deterministic, parallel via Send fan-out) + LLM risk ensemble + 3-layer filter that drops repeats, business-normal flags, and unsupported claims. Final output: a ranked risk list with severity, regulation source, and source citations; a downloadable DOCX report; structured JSON for API consumers.

### Anti-Hallucination Is Non-Negotiable

The system is designed so the LLM cannot lie about a document and have the lie pass through.

Every LLM-generated extraction includes a `_quotes` array with the verbatim text the model cites as source. A post-processor scans each quote against the document body. If the quote isn't there, the field is rejected — period. The 3-layer LLM-risk filter rejects any risk claim whose quoted evidence isn't in the package, repeats a finding from the deterministic domain checks, or describes a normal business condition.

This isn't a guardrail layer slapped on top — it's the trust contract between the model and the user, and it runs on every output. The `validation/` package is one of the most-edited folders in the repo precisely because we treat it as a first-class concern, not an afterthought.

### Demo Packages

Three pre-built scenarios are bundled in `test_data/demo_packages/`. Each is a one-click demo from the Upload tab:

- **Audit Demo** — Three invoices from the same supplier; the March one is 50% pricier than January and February. The package-level analyzer flags it as an over-billing pattern, and the chat answers *"Why is the March invoice more expensive?"* with cited line items.
- **DD Demo** — An NDA, a service agreement, and an amendment in an acquisition scenario. The DD assistant flags a hidden change-of-control trigger and an automatic-renewal red flag, and the synthesizer writes an executive summary in three paragraphs.
- **Compliance Demo** — Two contracts; one is missing GDPR Article 28 sub-processor language. Domain check #8 detects it, and the report includes the exact regulatory citation.

End-to-end demo time on AMD MI300X: **30–90 seconds** per package.

### Track 1 + Build in Public + Hugging Face Special Prize

**Track 1 — AI Agents & Agentic Workflows** is our primary submission. The track brief asks for projects that "move beyond simple RAG to build sophisticated AI agentic systems and workloads." PaperHawk fits the brief: 4 compiled graphs, 6 subgraphs, multi-agent DD orchestration, 5-tool agentic chat, and a registry-based deterministic check fabric. None of this is retrieval-only. The chat *is* an agent; the DD assistant is a multi-agent system; the pipeline is a typed-state orchestration.

**Ship It + Build in Public** is a natural cross-track fit. The repo is MIT licensed and public on GitHub. We're publishing a technical walkthrough and at least two updates on X / LinkedIn — tagging `@AIatAMD` and `@lablab` — covering two design choices that don't usually appear in hackathon RAG demos: the LangGraph Send-API parallelism for the deterministic check fan-out, and the post-hoc citation validator for the chat tool outputs.

**Hugging Face Special Prize**: deployed as a Streamlit Space under the `lablab-ai-amd-developer-hackathon` organization. Public, runnable in the browser, no signup required. The Space carries the same `paperhawk.jpeg` cover and points at our vLLM endpoint; visitors can drive the three demo packages from the front page.

One codebase, one MIT license, three prize pools.

### Tech Stack

| Layer | Choice |
|---|---|
| **Orchestration** | LangGraph 0.6 (4 compiled graphs, 6 subgraphs, AsyncSqliteSaver) |
| **LLM** | Qwen 2.5 14B Instruct on vLLM (AMD Instinct MI300X, ROCm) |
| **Embedding** | BAAI/bge-m3 (multilingual, 1024-dim, sentence-transformers) |
| **Retrieval** | ChromaDB + BM25 hybrid with Reciprocal Rank Fusion |
| **Schemas** | Pydantic v2 with field aliases for the `_quotes` JSON contract |
| **UI** | Streamlit 5-tab + async runtime + long-lived background event loop |
| **Deploy** | Hugging Face Spaces (Streamlit SDK) + AMD Developer Cloud (vLLM container) |
| **Testing** | pytest 8 (61 PASS in CI without any LLM), Playwright UI smoke tests |
| **License** | MIT |

### Built By

**Team CsimpiCsirkek**:

- **Vince Nándorfi** — Lead, LangGraph architecture, AMD adaptation
- **Tamás Vitai**
- **Gábor Murcsik**

---

## Technology & Category Tags

`agentic-ai` · `multi-agent` · `langgraph` · `qwen` · `amd-mi300x` · `vllm` · `rocm` · `huggingface-spaces` · `document-intelligence` · `streamlit` · `python` · `mit-license`

---

## Tracks Targeted

| Track / Prize | Status | Rationale |
|---|---|---|
| **Track 1 — AI Agents & Agentic Workflows** | Primary submission | Multi-agent system, 4 compiled graphs, 6 subgraphs, 5-tool agentic chat — well past the "simple RAG" line |
| **Ship It + Build in Public** | Cross-track | MIT-licensed public GitHub repo + technical walkthrough + ≥2 social posts tagging `@AIatAMD` and `@lablab` |
| **Hugging Face Special Prize** | Special category | Streamlit Space published under the `lablab-ai-amd-developer-hackathon` HF organization |

---

## Submission Checklist

| Item | Status | Notes |
|---|---|---|
| Project Title | DONE | `PaperHawk` |
| Short Description | DONE | 247 characters, A+C blend |
| Long Description | DONE | 10 sections, builder-energy tone |
| Cover Image | DONE | `paperhawk.jpeg` (2048 × 819 px) |
| Technology & Category Tags | DONE | 12 tags |
| Public GitHub Repository | DONE | `github.com/nandorfivince/paperhawk` |
| Video Presentation | TODO | Demo walkthrough video |
| Slide Presentation | TODO | 5–8 slide deck |
| Demo Application URL | TODO | HF Space public URL |
| HF Space URL | TODO | Under `lablab-ai-amd-developer-hackathon` org |

---

## Submission URLs (filled at submission time)

- **GitHub repo**: https://github.com/nandorfivince/paperhawk
- **Hugging Face Space**: *(to be added)*
- **Demo video**: *(to be added)*
- **Slide deck**: *(to be added)*
- **Live application URL**: *(same as HF Space URL)*

---

*This document is the canonical submission brief. Paste sections directly into the lablab.ai project page when filing the submission.*
