"""Embedding model — sentence-transformers, runs locally, offline-friendly.

Default: ``BAAI/bge-m3`` (2.27 GB, 1024 dim, multilingual incl. EN/HU/DE/FR/...).
Pre-downloaded at Docker build time → no network call at runtime.

Implements LangChain's ``Embeddings`` interface so the Chroma store and the
RAG subgraph can use it natively.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer

from config import settings


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Singleton model loader — first call ~2-5 seconds, subsequent calls instant."""
    return SentenceTransformer(settings.embedding_model)


class SentenceTransformerEmbeddings(Embeddings):
    """LangChain Embeddings adapter on top of sentence-transformers."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Batch-embed documents (faster than per-chunk encoding)."""
        model = _get_model()
        # convert_to_numpy=True → list[ndarray]; .tolist() → list[list[float]]
        vectors = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query (used by the chat search_documents tool)."""
        return self.embed_documents([text])[0]


def build_embeddings() -> SentenceTransformerEmbeddings:
    return SentenceTransformerEmbeddings()
