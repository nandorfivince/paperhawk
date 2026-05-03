# Hugging Face Space deployment

The Streamlit app deploys to a **Hugging Face Space** under the
`lablab-ai-amd-developer-hackathon` organization. This is **mandatory** for
the Hugging Face Special Prize and convenient as the public demo URL.

## 1. Prerequisites

- Hugging Face account
- Membership in the **AMD Developer Hackathon** HF organization
  ([join here](https://huggingface.co/login?next=%2Forganizations%2Flablab-ai-amd-developer-hackathon%2Fshare%2FELARrxoRIHvseSHRhANJYFEZQazsQIYhJf))
- A running vLLM endpoint on the AMD MI300X (see `qwen-vllm-deployment.md`)

## 2. Create the Space

1. Hugging Face → Spaces → New Space
2. Owner: `lablab-ai-amd-developer-hackathon`
3. Space name: `paperhawk`
4. License: MIT
5. SDK: **Streamlit**
6. Hardware: **CPU basic** (free) — vLLM runs on MI300X, the Space only hosts the UI

## 3. Push the code

```bash
git remote add space https://huggingface.co/spaces/lablab-ai-amd-developer-hackathon/paperhawk
git push space main
```

The Space auto-builds from the repo using `requirements.txt` and runs
`app.py` (or, in our layout, configures Streamlit to start `app/main.py`).

## 4. Set Space env vars

In the Space → Settings → Variables and secrets, add:

```
LLM_PROFILE=vllm
VLLM_BASE_URL=http://<mi300x-public-ip>:8000/v1
VLLM_MODEL=Qwen/Qwen2.5-14B-Instruct
VLLM_API_KEY=<the api key you set on the vLLM server>
EMBEDDING_MODEL=BAAI/bge-m3
```

Mark `VLLM_API_KEY` as a **secret** (not a regular variable).

## 5. Space front-matter

Edit the `README.md` to start with the HF Spaces front-matter:

```yaml
---
title: Document Intelligence (AMD Edition)
emoji: 🔍
colorFrom: red
colorTo: yellow
sdk: streamlit
sdk_version: 1.40.0
app_file: app/main.py
pinned: false
license: mit
short_description: Multi-document due diligence with LangGraph + Qwen on AMD MI300X
tags:
  - langgraph
  - agentic
  - rag
  - qwen
  - amd
  - document-intelligence
---
```

(The current README.md is the project README; this front-matter goes on top
when the repo is mirrored to the HF Space.)

## 6. Verify the Space

After the build finishes (~3-5 minutes):

1. Open `https://huggingface.co/spaces/lablab-ai-amd-developer-hackathon/paperhawk`
2. Click the **Audit Demo** button → it should run end-to-end and produce
   risks + a report.
3. Open the **Chat** tab → ask a question → the answer should include
   `[Source: filename.pdf]` citations.

## 7. Resource tier

The free CPU basic tier (16 GB RAM, 2 vCPU) handles:

- BGE-m3 embedding (~2.3 GB on first load)
- ChromaDB (small index)
- Streamlit UI

The vLLM model runs on the MI300X, **not** here. The Space just renders the
UI and proxies requests to the vLLM endpoint.

If the free tier is too tight on memory, upgrade to **CPU upgrade** ($0.03/h).

## 8. Sleep mode mitigation

A free Space sleeps after 48 hours of inactivity. The first request after
sleep takes ~30-60 seconds to wake. Mitigations:

- Share the Space link in your Build-in-Public posts → continuous traffic →
  less likely to sleep.
- Set up a 30-minute external ping (e.g. UptimeRobot) the day before
  judging.

## 9. The HF Special Prize is like-driven

Once the Space is live:

1. Share the URL on X / LinkedIn (tag `@lablab` and `@AIatAMD`).
2. Ask your followers to like the Space.
3. The Space with the most likes at the end of the hackathon wins:
   - 1st: Reachy Mini Wireless robot + 6 months HF PRO + $500 HF credit
   - 2nd: 3 months HF PRO + $300 credit
   - 3rd: 2 months HF PRO + $200 credit

## 10. Submission to lablab

When submitting on lablab.ai, paste the Space URL into the **Application
URL** and **Hugging Face Space link** fields. This is mandatory for the HF
prize qualification.
