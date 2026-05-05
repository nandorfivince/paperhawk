<p align="center">
  <img src="https://raw.githubusercontent.com/nandorfivince/paperhawk/main/paperhawk.jpeg" alt="PaperHawk" width="900">
</p>

<h1 align="center">PaperHawk</h1>

<p align="center">
  <strong>Agentic document intelligence on AMD MI300X</strong><br>
  Multi-document due diligence with deterministic compliance rules and a 6-layer anti-hallucination stack.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT">
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/LangGraph-0.6-green.svg" alt="LangGraph">
  <img src="https://img.shields.io/badge/AMD-MI300X-red.svg" alt="AMD MI300X">
  <img src="https://img.shields.io/badge/Qwen-2.5%2014B-purple.svg" alt="Qwen 2.5 14B">
</p>

<p align="center">
  Built for the <strong>AMD Developer Hackathon × lablab.ai</strong> (May 2026).
</p>

---

## What is PaperHawk?

PaperHawk is an **agentic multi-document intelligence platform** for auditors, lawyers, tax advisors, and DD analysts. It processes 3–50 PDFs simultaneously and detects **cross-document red flags humans miss** — like a 57.5% price drift across three invoices from the same supplier — using a multi-agent LangGraph orchestration on top of Qwen 2.5 14B Instruct served via vLLM on AMD Instinct MI300X.

It is **not** a chatbot. It is a typed-state, multi-graph reasoning system with deterministic compliance rules, verbatim source citations, and a quote validator that catches LLM hallucinations before they reach the user.

## Why it matters

A senior auditor needs ~8 hours to thoroughly review a 50-page invoice/contract package. ChatGPT, Copilot, and Harvey handle one document at a time, hallucinate citations, and lack jurisdiction-specific compliance knowledge. PaperHawk handles the entire package, applies 14 statutory rules hand-coded in Python, and finishes a 3-document audit in **23.3 seconds** (61.7× faster than manual review) — with auditor-grade citations and ISA/GDPR/HU-VAT mappings.

---

## Technical highlights

- **Multi-agent LangGraph 0.6 orchestration** — 4 compiled graphs (pipeline, chat, DD, package_insights) + 6 reusable subgraphs with Send-API parallelism
- **5-tool agentic chat** with strict `[Source: filename.pdf]` citations validated by a post-processor (no provenance → no answer)
- **6-layer anti-hallucination stack** — `temperature=0`, verbatim source quotes, field-level confidence, plausibility validators, 3-stage LLM-risk filter chain, quote validator
- **Provider abstraction** with `configurable_alternatives` — vLLM (production) / Ollama (local dev) / dummy (CI) — swap with one env var, zero code changes
- **AMD Instinct MI300X via vLLM** — 192 GB HBM3, 27.6 GB model + 141 GB available KV cache, 307 t/s prompt + 252 t/s generation, 30.4% prefix cache hit rate
- **61.7× speedup** vs manual audit on a 3-document package (23.3 sec vs ~24 min)
- **Hugging Face Space deployable** with Docker SDK + Git LFS for binary assets

## Domain highlights

- **14 deterministic statutory rules** hand-coded in Python (NOT prompt-engineered) — ISA 240/320/500 audit standards, HU VAT Act §169 mandatory invoice elements, Ptk. 6:98 disproportionate penalty clauses, Art. 22 tax-ID validation, GDPR Article 28 sub-processor language, Incoterms 2020, AML sanctions list (EU/OFAC fuzzy match)
- **Cross-document red flag detection** — three-way matching (invoice + delivery note + PO), package-level pricing anomalies, duplicate-invoice detection (ISA 240), change-of-control trigger detection (M&A DD)
- **Multi-agent DD assistant** — 4 specialists (audit / legal / compliance / financial) coordinated by a supervisor and a synthesizer for executive summaries
- **Auditor-grade citations** — every finding maps to a regulation source (HU VAT Act §169, ISA 500, GDPR Art. 28, etc.) with verbatim source quote
- **Multilingual ingest** — EN / HU / DE OCR via Tesseract, native PDF + DOCX, vision-first scanned-PDF fallback

---

## Try the live demo

**Public Hugging Face Space** (no signup, runs in browser):

→ <https://huggingface.co/spaces/Vincsipe/paperhawk>

Click **Audit Demo** in the Quick demo section. Three pre-bundled invoices process in ~25 seconds and you'll see the cross-doc 57.5% price drift flag, the 14 deterministic checks, and the auditor-grade citations.

Backed by an AMD MI300X vLLM endpoint serving Qwen 2.5 14B Instruct.

---

## Run it locally

Two options depending on whether you have a GPU or just want a quick smoke test.

### Quick demo (~3 minutes, no GPU needed)

Uses the **deterministic dummy provider** — runs the full pipeline, all 14 domain checks, and the multi-agent orchestration without any LLM calls. Good for verifying the system runs end-to-end.

```bash
git clone https://github.com/nandorfivince/paperhawk
cd paperhawk
make install
LLM_PROFILE=dummy make dev
```

Open <http://localhost:8501> → **Audit Demo** button. Result in ~5 seconds (dummy provider returns deterministic test data).

### Full demo (~10 minutes, ~16 GB VRAM recommended)

Uses **Ollama with Qwen 2.5 14B Instruct** (the same model we deployed to AMD MI300X via vLLM). On a consumer GPU like NVIDIA RTX 4090 / RTX PRO 4500 (32 GB VRAM) you'll see real, production-grade multi-agent reasoning.

```bash
git clone https://github.com/nandorfivince/paperhawk
cd paperhawk
make install

# Pull the model (one-time, ~9 GB download)
ollama pull qwen2.5:14b-instruct

# Run the app pointed at Ollama
LLM_PROFILE=ollama OLLAMA_MODEL=qwen2.5:14b-instruct \
  streamlit run app/main.py --server.port=8501 --server.fileWatcherType=none
```

Open <http://localhost:8501> → **Audit Demo** button.

**Expected results on an RTX PRO 4500 (32 GB GDDR7)**:

- Audit Demo: ~80 seconds for 3 invoices, 17.5× speedup vs manual
- 8 risk findings (2 HIGH, 4 MEDIUM, 2 LOW), HU VAT Act §169 mappings
- Cross-doc package-level analyzer flags the 57.5% price-drift red flag
- Quote validator catches 4 of 6 hallucinated citations and downgrades them to `low` confidence

(On AMD MI300X via vLLM: ~23 seconds, 61.7× speedup. 5× faster than Ollama on consumer GPU.)

### Docker compose (alternative)

```bash
make run-local
```

Spins up the Streamlit app + Ollama in containers. First run pulls the model (~9 GB).

---

## Documentation

| Document | What it covers |
|---|---|
| [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) | LangGraph multi-graph design, 14 domain checks, anti-hallucination stack, multi-agent DD |
| [`docs/AMD_DEPLOYMENT.md`](../docs/AMD_DEPLOYMENT.md) | How we deployed Qwen 2.5 14B via vLLM on AMD Instinct MI300X (DigitalOcean-powered AMD Developer Cloud) |
| [`docs/HUGGINGFACE_DEPLOYMENT.md`](../docs/HUGGINGFACE_DEPLOYMENT.md) | How we deployed the Streamlit app as a public Hugging Face Space |

For the full submission brief with TAM/SAM, competitor analysis, and the live deployment validation results, see [`docs/SUBMISSION.md`](../docs/SUBMISSION.md).

---

## License

MIT — see [`LICENSE`](../LICENSE). Use, fork, deploy commercially or non-commercially.

## Built by

**Team csimpicsirkek** (`PÁKÁK the AI warriors!` on the lablab.ai platform):

- Vince Nándorfi — lead, LangGraph architecture, AMD adaptation
- Erika Nagy — silent partner
- Tamás Vitai
- Gábor Murcsik

For the AMD Developer Hackathon × lablab.ai, May 2026.
