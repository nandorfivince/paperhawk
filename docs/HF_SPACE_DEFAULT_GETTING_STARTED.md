# HF Space Default Getting Started — Snapshot 2026-05-05

A `lablab-ai-amd-developer-hackathon/paperhawk` Space létrehozása után a HF Spaces egy default "Get Started" útmutatót mutat. Ezt mentjük el itt referenciaként, mert a default Dockerfile-mintája hasznos referencia a paperhawk Dockerfile átírásához (port 8501 → 7860, user-setup pattern).

**Forrás**: a Space oldal alján, a default-README után jelent meg.

**URL**: https://huggingface.co/spaces/lablab-ai-amd-developer-hackathon/paperhawk

**Kontextus**: a Space frissen létrehozva, Docker SDK + Blank template + `Real-DI-Audit/14 rules/6 anti-halluc/LangGraph/Qwen/MI300X` short description.

---

## Get started with your Docker Space!

Your space has been created, follow these steps to get started (or read the full [documentation](https://huggingface.co/docs/hub/spaces-sdks-docker))

### Start by cloning this repo by using:

**HTTPS:**

```bash
git clone https://huggingface.co/spaces/lablab-ai-amd-developer-hackathon/paperhawk
```

**SSH:**

```bash
git clone git@hf.co:spaces/lablab-ai-amd-developer-hackathon/paperhawk
```

### Make sure you're CLI v2.x.x or above:

```bash
curl -LsSf https://hf.co/cli/install.sh | sh
```

### Download the Space:

```bash
hf download lablab-ai-amd-developer-hackathon/paperhawk --repo-type=space
```

---

## Let's create a simple Python app using FastAPI

### `requirements.txt`

```
fastapi
uvicorn[standard]
```

> **Hint:** You can also create the requirements file directly in your browser.

### `app.py`

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def greet_json():
    return {"Hello": "World!"}
```

> **Hint:** You can also create the app file directly in your browser.

---

## Create your Dockerfile

```dockerfile
# Read the doc: https://huggingface.co/docs/hub/spaces-sdks-docker
# you will also find guides on how best to write your Dockerfile

FROM python:3.9

RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

COPY --chown=user ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY --chown=user . /app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
```

> **Hint:** Alternatively, you can create the Dockerfile file directly in your browser.

---

## Then commit and push

```bash
git add requirements.txt app.py Dockerfile
git commit -m "Add application file"
git push
```

> Finally, your Space should be running on this page after a few moments!

---

## App port

> Your Docker Space needs to listen on port `7860`.

## Personalize your Space

Make your Space stand out by customizing its emoji, colors, and description by **editing metadata** in its `README.md` file.

## Documentation

Read the full documentation for Docker Spaces [here](https://huggingface.co/docs/hub/spaces-sdks-docker).

---

## Mit jelent ez nekünk (paperhawk-specifikus megjegyzések)

### A default Dockerfile vs a paperhawk Dockerfile

A paperhawk meglévő Dockerfile-ja **fejlettebb** mint a default-példa:

| Aspektus | HF default | Paperhawk |
|---|---|---|
| Python version | `python:3.9` | `python:3.12-slim` (modernebb) |
| User setup | `useradd -m -u 1000 user` + `USER user` (non-root, security best-practice) | NINCS (root user) |
| OS-deps | nincs | `tesseract-ocr` + `poppler-utils` + `libmupdf-dev` (PDF + OCR) |
| Pre-download | nincs | `BAAI/bge-m3` 2.27 GB (build-time) |
| App | `uvicorn` FastAPI | `streamlit` |
| Port | **`7860`** | **`8501`** → **átírva 7860-ra a HF Space-nek** (2026-05-05) |

### A 2 fő átírás amit a paperhawk Dockerfile-on csinálni kellett

1. **Port-átállítás 8501 → 7860** (kész, 2026-05-05):
   - `EXPOSE 8501` → `EXPOSE 7860`
   - `--server.port=8501` → `--server.port=7860`
   - `HEALTHCHECK ... http://localhost:8501/_stcore/health` → `http://localhost:7860/_stcore/health`

2. **(opcionális) User-setup hozzáadása** security best-practice szempontból:
   - `RUN useradd -m -u 1000 user`
   - `USER user`
   - `ENV PATH="/home/user/.local/bin:$PATH"`
   - `COPY --chown=user ...`
   - **A HF Spaces NEM követeli kötelező módon**, és a paperhawk-stack root-ként is jól fut.

### A README.md front-matter

A HF Spaces megköveteli a `README.md` tetején egy YAML front-matter-t. A paperhawk `README.md` tetejére beillesztve (2026-05-05):

```yaml
---
title: PaperHawk
emoji: 🦅
colorFrom: red
colorTo: orange
sdk: docker
pinned: false
license: mit
short_description: Real-DI-Audit/14 rules/6 anti-halluc/LangGraph/Qwen/MI300X
---
```

A meglévő paperhawk `README.md`-tartalom (project README) ezután következik. A front-matter csak a HF Space-nek szól, GitHub-on is renderelhető (a YAML-t code-block-ként mutatja).

### A clone + push workflow a paperhawk-on

A meglévő paperhawk GitHub-repón (`nandorfivince/paperhawk`) hozzáadunk egy új remote-ot:

```bash
cd ~/development/<host-paperhawk-path>
git remote add space https://huggingface.co/spaces/lablab-ai-amd-developer-hackathon/paperhawk
git push space main
```

A push első futáskor authenticálni kér — a HF Hub-token-t kéri, amit a Vincsipe accountból lehet generálni a https://huggingface.co/settings/tokens-en (új Token, "Write" scope).

### App port környezeti változó

A HF Spaces a `7860`-as portot várja default. A paperhawk `streamlit` parancs ki van egészítve a `--server.port=7860` flag-gel a `Dockerfile`-ben (2026-05-05).

### HF Spaces hardware

CPU Basic = free tier, 16 GB RAM, 2 vCPU. Bőven elég a paperhawk-Streamlit-jéhez (~3-5 GB RAM-fogyasztás bge-m3 + ChromaDB + Streamlit). A vLLM az AMD MI300X-en fut **külön**, a Space `VLLM_BASE_URL` Secret-en keresztül hivatkozik rá.

### Sleep mode

A free Space 48 órás inaktivitás után alvó-módba kerül. Az első request a felébredés után 30-60 sec. A bíráskodás alatt érdemes **periodikusan** pingelni a Space-t (pl. UptimeRobot 30 perces intervallum), vagy a Build-in-Public posztokon megosztani hogy organic-traffic-al ébren tartsuk.
