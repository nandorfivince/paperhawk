# Build in Public · Post 1 — Build Window Opens

**Timing**: post on or just after the AMD Hackathon kick-off (May 4, 6:00 PM CEST).
**Order**: post on **X first**, then LinkedIn ~30 minutes later.
**Why**: X moves fast, LinkedIn rewards a slightly longer-form follow-up.

This is the first of three planned Build-in-Public posts:

1. **Post 1** (this file) — build window opens · stack-introduction · GitHub link
2. **Post 2** (mid-week, ~May 7-8) — technical deep-dive on one design choice (LangGraph Send-API parallelism for the deterministic check fan-out)
3. **Post 3** (May 10, after submit) — final demo · HF Space · pitch-recap

Mandatory tags ([per the official Build in Public requirement](https://lablab.ai/event/amd-developer-hackathon)):

| Platform | Required tags |
|---|---|
| X | `@lablab` + `@AIatAMD` |
| LinkedIn | `lablab.ai` + `AMD Developer` (showcase pages) |

---

## Variant A — X (Twitter)

> Character budget: 280 — version below uses 269 chars including handles + hashtags.

```
Build window opens.

Putting our LangGraph-native, multi-agent document intelligence
platform on AMD Instinct MI300X for the @AIatAMD x @lablab
hackathon.

Qwen 2.5 14B on vLLM. 14 deterministic domain checks. 5+1
anti-halluc layers. MIT, public.

→ github.com/nandorfivince/paperhawk

#AMDHackathon #BuildInPublic
```

### X variant alternatives (in case the first doesn't fit)

**Punchy / 240 char:**

```
PaperHawk — multi-agent document intelligence on @AIatAMD MI300X.

Qwen 2.5 14B + LangGraph 0.6 + 14 deterministic domain checks.
Build window starts now for the @lablab hackathon.

Open source · MIT · public repo.

→ github.com/nandorfivince/paperhawk

#AMDHackathon #BuildInPublic
```

**Tech-detail / 270 char:**

```
We built PaperHawk: 4 LangGraph graphs, 6 subgraphs, 14
deterministic domain checks, multi-agent DD assistant.

Now porting it to @AIatAMD Instinct MI300X via vLLM for the
@lablab hackathon.

Qwen 2.5 14B inside. MIT, public.

→ github.com/nandorfivince/paperhawk

#AMDHackathon #BuildInPublic
```

---

## Variant B — LinkedIn (long form)

> Character budget: 3000. Version below is ~1280 chars + tags. Reads as a proper builder-energy update for technical recruiters and AI-engineering peers.

```
Build window opens.

For the next week we're putting PaperHawk — our LangGraph-native, 
multi-agent document intelligence platform — on AMD Instinct MI300X 
GPUs for the AMD Developer Hackathon × lablab.ai.

The premise is simple: most "document AI" today is RAG with extra 
steps. Retrieve a passage, summarize it, hope it's right. That's 
fine for FAQ chatbots. It's not fine for auditors, due-diligence 
teams, or anyone who has to cross-reference a folder of contracts 
and invoices and trust the answer.

PaperHawk is built for the second case:

→ 4 compiled LangGraph 0.6 graphs (pipeline / chat / DD / package)
→ 14 deterministic domain checks (ISA 240/500/320, GDPR Article 28, 
   Incoterms 2020, AML sanctions)
→ 5+1 anti-hallucination layers — every LLM claim must cite a 
   verbatim quote from the document, or it gets dropped
→ 5-tool agentic chat with strict [Source: filename.pdf] citations
→ Multi-agent DD assistant: 4 specialists + supervisor + synthesizer

Stack:
→ Qwen 2.5 14B Instruct served via vLLM on AMD MI300X (ROCm)
→ BAAI/bge-m3 multilingual embeddings
→ Streamlit 5-tab UI, deployable as a Hugging Face Space
→ MIT licensed, English-first, multilingual fallback

Three of us have shipped together for nearly a decade. We're not 
new to building things. We're using this hackathon to put our 
agentic DI platform on AMD's open compute stack and see how far it 
goes.

We'll be sharing a technical walkthrough mid-week — including why 
LangGraph's Send-API parallelism beat sequential domain dispatch in 
our benchmarks.

Repo (public): https://github.com/nandorfivince/paperhawk

#AMDHackathon #BuildInPublic #LangGraph #Qwen #AMDInstinct #lablab
```

**Don't forget**: in the LinkedIn post composer, **tag the company pages**:

- `lablab.ai` → https://www.linkedin.com/company/lablab-ai/
- `AMD Developer` (showcase page) → https://www.linkedin.com/showcase/amd-developer/

These appear as `@lablab.ai` and `@AMD Developer` in the post — LinkedIn auto-completes them when you start typing.

---

## Image / media to attach

For both X and LinkedIn, attach **one image**: the cover slide from the deck.

```bash
# Generate it from slides.html (see docs/slides/README.md for the script):
python -c "<<see docs/slides/README.md cover-PNG snippet>>"
# Output: docs/slides/01_cover.png
```

Alternative for X (which compresses heavily): use the `paperhawk.jpeg` directly — it's already wide-format (2048×819) and reads well on mobile.

---

## Posting checklist

| Step | Status |
|---|---|
| Cover image generated (`docs/slides/01_cover.png`) | TODO before posting |
| GitHub repo public + README hero visible | DONE |
| `@lablab` + `@AIatAMD` typed correctly on X | TODO at post-time |
| `lablab.ai` + `AMD Developer` company pages tagged on LinkedIn | TODO at post-time |
| Repo URL works in private/incognito browser (sanity-check public visibility) | TODO before posting |
| `#AMDHackathon` `#BuildInPublic` hashtags both included | DONE |

---

## What this post is NOT

- Not a marketing pitch. It's a technical announcement.
- Not "we hope to win". It's "we built this, here's what it does, watch this space."
- Not asking for likes. The HF Space is where like-voting happens (different track / different prize).

The job of this post: **plant a flag**. We're building. We're public. We've shipped together before. Now we're doing it on AMD GPUs.
