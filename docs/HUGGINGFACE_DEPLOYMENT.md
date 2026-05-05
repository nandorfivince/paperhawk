# Hugging Face Spaces Deployment

How we deployed the PaperHawk Streamlit application as a public Hugging Face Space, with the AMD MI300X vLLM endpoint as its inference backend.

---

## What you get

- **Public Space URL** — a Streamlit app anyone can use in a browser, no signup
- **Free CPU Basic tier** — 16 GB RAM, 2 vCPU. The app runs here; the LLM runs on AMD MI300X via vLLM (separate Cloud).
- **Two paths**: under the `lablab-ai-amd-developer-hackathon` org (Plan A — qualifies for HF Special Prize), or under your personal account (Plan B — fallback if the org has hardware-quota issues)

Live example: <https://huggingface.co/spaces/Vincsipe/paperhawk>

---

## Prerequisites

1. Hugging Face account (free)
2. **Optional**: membership in the `lablab-ai-amd-developer-hackathon` org if submitting to the AMD Developer Hackathon (Plan A). The HF Special Prize requires the Space to live under this org.
3. A running vLLM endpoint on AMD MI300X — see [`AMD_DEPLOYMENT.md`](AMD_DEPLOYMENT.md)
4. The PaperHawk repo cloned locally with `Dockerfile`, `README.md`, and `app/main.py`

---

## Step 1 — Create the Space

Go to <https://huggingface.co/new-space> (or, if you're an org member, click `+ New` → `New Space` from the org page).

**Configuration**:

| Field | Value |
|---|---|
| Owner | `lablab-ai-amd-developer-hackathon` (Plan A) or your personal handle (Plan B) |
| Space name | `paperhawk` |
| Short description | `Real-DI-Audit/14 rules/6 anti-halluc/LangGraph/Qwen/MI300X` |
| License | `mit` |
| **Space SDK** | **Docker** (not Streamlit, not Gradio — see step 2) |
| **Template** | **Blank** (we ship our own Dockerfile) |
| Hardware | CPU Basic (free, 16 GB RAM) |
| Visibility | Public (required for the HF Special Prize) |

Click **Create Space**. You'll get an empty repo at:

```
https://huggingface.co/spaces/<owner>/paperhawk
```

**Why Docker SDK and not Streamlit-template?** As of 2026, the HF Spaces "Streamlit" SDK lives under the Docker tab as a managed template. We bypass the template because PaperHawk needs custom OS dependencies (Tesseract OCR for EN/HU/DE, poppler-utils for table extraction, libmupdf for PDFs) that the templated builder doesn't include. Our own Dockerfile is faster to debug and gives us a deterministic base image.

---

## Step 2 — Configure the Dockerfile for HF Spaces

The PaperHawk Dockerfile is HF-Spaces-ready out of the box, with one critical detail: **port 7860**.

```dockerfile
# syntax=docker/dockerfile:1.6
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# OS deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-hun tesseract-ocr-deu \
    poppler-utils libmupdf-dev curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install -r requirements.txt

# Pre-download the embedding model so the first user request isn't slow
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

COPY . .

# HF Spaces expects port 7860 (NOT Streamlit's default 8501)
EXPOSE 7860
CMD ["streamlit", "run", "app/main.py", \
     "--server.address=0.0.0.0", \
     "--server.port=7860", \
     "--server.headless=true"]
```

**Why 7860?** HF Spaces' Docker hosting only routes traffic to port 7860 — the Streamlit default 8501 is invisible to the public URL. This is a one-line fix that's easy to miss.

---

## Step 3 — Configure the README YAML front-matter

HF Spaces reads the YAML block at the top of `README.md` to configure the Space card and build behavior. PaperHawk's:

```yaml
---
title: PaperHawk
emoji: 🦅
colorFrom: red
colorTo: yellow
sdk: docker
pinned: false
license: mit
short_description: Real-DI-Audit/14 rules/6 anti-halluc/LangGraph/Qwen/MI300X
---
```

**Critical**: `colorTo` must be one of `[red, yellow, green, blue, indigo, purple, pink, gray]`. We initially used `orange` (because the AMD brand color is orange) — HF rejected the YAML as invalid, and the Space card fell back to a generic theme **with the YAML rendered as a Markdown table at the top of the page**. Fixed by changing to `yellow`.

If the Space's main page shows a `title | PaperHawk` table at the top, the YAML is invalid and HF can't parse it — check the `colorTo` value first.

---

## Step 4 — Set up Git LFS for binary assets

HF Spaces has a strict rule: every binary file (`*.png`, `*.pdf`, `*.pptx`, `*.docx`, `*.jpg`, `*.mp4`) must live in **Xet storage** via Git LFS, not as a regular Git blob. The cover PNG, the slide PDF, the demo packages — all of these get rejected without LFS.

On your local machine:

```bash
# One-time, in any repo with binary files
sudo apt install git-lfs   # or `brew install git-lfs` on macOS
git lfs install
```

In the PaperHawk repo:

```bash
git lfs track "*.png" "*.pdf" "*.pptx" "*.docx" "*.jpeg" "*.jpg" "*.mp4"
git add .gitattributes
git commit -m "Track binary files via LFS"
```

**Important**: `git lfs track` only updates `.gitattributes`. Existing commits with binaries-as-Git-blob are still rejected by HF. Migrate the entire history:

```bash
git lfs migrate import --include="*.png,*.pdf,*.pptx,*.docx,*.jpeg,*.jpg,*.mp4"
```

This rewrites the HEAD commit so the binaries are LFS-blobs. New `git push` will upload them via Xet.

**Files over 10 MB**: HF Spaces also enforces a 10 MB hard limit per file even via LFS for the free Spaces tier. Any single video over 10 MB will be rejected. If you have demo videos, keep them as separate uploads on YouTube/Vimeo and link from the Space description.

---

## Step 5 — Add the Space as a git remote and push

```bash
# Add a remote for the Space (token embedded in URL avoids dual auth-prompts)
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxx   # generate at https://huggingface.co/settings/tokens (Write scope, fine-grained, with org access if Plan A)
git remote add space https://<your-hf-username>:${HF_TOKEN}@huggingface.co/spaces/<owner>/paperhawk

# Push to the Space
git push --force space main
```

**Why token in URL?** Git LFS uses a separate authentication channel from the regular Git push. Without the token in the URL, Git prompts for credentials twice and one of them silently times out. Putting the token in the URL handles both.

The first push uploads ~9 MB of LFS objects (the cover image, slide PDF, sample PDFs, sample DOCX). Subsequent pushes are fast (cached on HF's side).

---

## Step 6 — Add Space secrets

The app reads its LLM provider config from environment variables. In the Space:

**Settings** (top-right, on the Space page) → **Variables and secrets** → **+ New variable** for each:

| Key | Value | Type |
|---|---|---|
| `LLM_PROFILE` | `vllm` | Variable |
| `VLLM_BASE_URL` | `http://<MI300X_DROPLET_IP>:8000/v1` | Variable |
| `VLLM_MODEL` | `Qwen/Qwen2.5-14B-Instruct` | Variable |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Variable |
| `VLLM_API_KEY` | `sk-paperhawk-2026` (the same token you passed to vLLM `--api-key`) | **Secret** |

The `VLLM_API_KEY` must be a **Secret**, not a Variable — Secrets are masked in the UI and not exposed via the public Space metadata.

After saving, the Space rebuilds automatically (~5 minutes for first build, faster for subsequent).

---

## Step 7 — Wait for the build, then verify

The first build pulls and installs everything — Python 3.12-slim, OS deps, PyTorch CPU wheel, the BAAI/bge-m3 model (~2.3 GB pre-download), and the rest of `requirements.txt`. Expect 8–15 minutes for the cold build.

Watch the build logs in the Space → **Logs** tab. When you see `streamlit run app/main.py` and `You can now view your Streamlit app in your browser` the Space is up.

Open the Space URL in a browser and click **Audit Demo**. If the vLLM endpoint is reachable, you'll see results in 20–25 seconds.

If you get an error like `Connection refused` or a long hang, check:

1. The MI300X droplet is running and `vllm serve` is up (SSH in, look at the SSH window from `AMD_DEPLOYMENT.md` step 6)
2. The droplet's UFW has port 8000 open (`ufw status | grep 8000` from the droplet)
3. The `VLLM_BASE_URL` in Space Secrets matches the droplet's current public IP (which changes on every recreate-from-snapshot)

---

## Step 8 — Hide the YAML from the GitHub display (optional)

The YAML front-matter is needed for HF Spaces but **looks ugly on GitHub** — the renderer shows it as a `key | value` table at the top of the README, with no formatting.

Workaround: GitHub honors `.github/README.md` over the root `README.md` for the public repo display. We commit a copy of the README **without** the YAML block as `.github/README.md`:

```bash
mkdir -p .github
tail -n +12 README.md > .github/README.md   # skip the first 11 lines (the YAML + blank line)
# (optionally edit .github/README.md to use absolute raw-image URLs for paperhawk.jpeg)
git add .github/README.md
git commit -m "Add .github/README.md to hide HF YAML on GitHub display"
git push origin main
```

Now GitHub shows `.github/README.md` (clean), and HF Spaces still reads the root `README.md` (with YAML). One file, two faces.

---

## Plan A vs Plan B

| Aspect | Plan A (org Space) | Plan B (personal Space) |
|---|---|---|
| Owner | `lablab-ai-amd-developer-hackathon/paperhawk` | `<your-handle>/paperhawk` |
| HF Special Prize | ✅ Qualifies | ❌ Disqualifies |
| Org-quota dependency | ⚠️ Yes (shared with other org Spaces) | ❌ Independent |
| Visibility | Public, on the org page | Public, on your profile |
| Setup steps | Same as above | Same as above |

If the org-quota is exhausted (we hit `null quota limit` 403 errors), the same code, same Dockerfile, same YAML, same env-var setup pushes to a personal Space and runs immediately. This was our Plan B safety net during the hackathon.

---

## Common pitfalls

- **"Build failed: app port 7860 not reachable"**: Your Dockerfile is binding to a different port (probably Streamlit's default 8501). Change `EXPOSE` and `CMD` to use 7860.
- **YAML rendered as a Markdown table on the Space main page**: The YAML is invalid. Most likely culprits: invalid `colorTo` (allowed: red/yellow/green/blue/indigo/purple/pink/gray, **not** orange), invalid `sdk`, missing `---` opening line, BOM/whitespace before the first `---`.
- **"binary files require Xet"**: You haven't run `git lfs track` + `git lfs migrate import` yet. The HF push rejects committed binaries that aren't LFS-blobs.
- **"Files larger than 10 MiB are not allowed"**: A single file is over 10 MB even after LFS. Move it out of the repo and link from the README.
- **"null quota limit" 403 error**: Org-level hardware quota is exhausted. Wait for capacity, ping a lablab admin in Discord, or push to a personal Space (Plan B).
- **App loads but "Connection refused" on Audit Demo**: The vLLM endpoint is down or the IP changed. SSH into the droplet and confirm `vllm serve` is running. Update `VLLM_BASE_URL` Secret if the IP rotated.
- **App loads but "401 Unauthorized" on every LLM call**: The `VLLM_API_KEY` Secret doesn't match the `--api-key` you passed to `vllm serve`. They have to be byte-for-byte identical.

---

## Cross-references

- [`docs/AMD_DEPLOYMENT.md`](AMD_DEPLOYMENT.md) — provisioning the AMD MI300X vLLM endpoint that this Space depends on
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — how the Streamlit app, the LangGraph multi-graph orchestrator, and the vLLM endpoint fit together
- [`docs/HF_SPACE_DEFAULT_GETTING_STARTED.md`](HF_SPACE_DEFAULT_GETTING_STARTED.md) — the canonical HF Spaces Quick Start that this guide builds on
- [`docs/SUBMISSION.md`](SUBMISSION.md) — full hackathon submission brief
