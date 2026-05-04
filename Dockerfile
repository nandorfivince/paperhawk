# syntax=docker/dockerfile:1.6
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# OS-level dependencies:
# - tesseract-ocr (eng + hun + deu): scanned PDF OCR fallback (multilingual demo support)
# - poppler-utils: pdfplumber table extraction
# - libmupdf-dev: PyMuPDF native lib
# - curl: healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-hun \
        tesseract-ocr-deu \
        poppler-utils \
        libmupdf-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps — CPU-only torch first (smaller image), then the rest
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install -r requirements.txt

# Sentence-transformers model pre-download (no runtime network call).
# BAAI/bge-m3 = 2.27 GB, 1024 dim, multilingual (EN/HU/DE/FR/...).
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('BAAI/bge-m3')"

# Source code
COPY . .

# Streamlit healthcheck — port 7860 for HF Space deployment (HF expects this)
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:7860/_stcore/health || exit 1

CMD ["streamlit", "run", "app/main.py", \
     "--server.address=0.0.0.0", \
     "--server.port=7860", \
     "--server.headless=true"]
