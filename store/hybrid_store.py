"""HybridStore — ChromaDB (vektor) + BM25Okapi (sparse) + RRF (k=60) fusion.

A `prototype-agentic` mintát követjük (rag/store.py:105-136):
  * vektor: ChromaDB PersistentClient, cosine distance
  * sparse: BM25Okapi (in-memory, rank-bm25 package)
  * fusion: Reciprocal Rank Fusion -- score = 1.0 / (60 + rank + 1)

Async-friendly: az add_chunks és search async-friendly (Chroma serializál belül).
A BM25 rebuild egy `asyncio.Lock` mögött zajlik — a Send API per-doc fan-out
párhuzamos add_chunks hívásait szerializálja.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

import chromadb
from rank_bm25 import BM25Okapi

from config import settings
from providers.embeddings import SentenceTransformerEmbeddings


# RRF konstans -- standard érték a litaratúrában
RRF_K = 60


class HybridStore:
    """Vektor + BM25 hibrid keresés (RRF fusion).

    Egy persistent ChromaDB collection-be tölti a chunkok embedding-jeit, és
    in-memory BM25 indexet épít a tokenizált szövegen. A search_hybrid a két
    rangsort RRF-fel fuzionálja.

    Az embedding modellt a `providers.embeddings.build_embeddings()` adja.
    """

    def __init__(
        self,
        chroma_path: str | None = None,
        collection_name: str | None = None,
        embeddings: SentenceTransformerEmbeddings | None = None,
    ):
        self.chroma_path = str(chroma_path or settings.chroma_path)
        self.collection_name = collection_name or settings.chroma_collection
        self._embeddings = embeddings
        self._client: chromadb.PersistentClient | None = None
        self._collection: Any = None

        # BM25 in-memory state
        self._bm25_corpus: list[list[str]] = []  # tokenized texts
        self._bm25_meta: list[dict] = []  # parallel metadata + raw text
        self._bm25: BM25Okapi | None = None

        # Concurrency: a BM25 rebuild kritikus szakasz
        self._bm25_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lazy init: csak az első használatkor töltjük be a Chroma client-et
    # ------------------------------------------------------------------

    def _ensure_init(self) -> None:
        if self._client is None:
            self._client = chromadb.PersistentClient(path=self.chroma_path)
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        if self._embeddings is None:
            from providers import get_embeddings
            self._embeddings = get_embeddings()

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Egyszerű szóhatár-alapú tokenizáció (kis-/nagybetű egységesítve)."""
        return re.findall(r"\w+", (text or "").lower())

    # ------------------------------------------------------------------
    # Add — async, párhuzamos Send-fan-out-tal hívható
    # ------------------------------------------------------------------

    async def add_chunks(self, chunks: list[dict]) -> int:
        """Chunk-okat hozzáad mind a ChromaDB-hez, mind a BM25 indexhez.

        Args:
            chunks: [{"text": str, "metadata": {"source": ..., "chunk_index": ..., ...}}, ...]

        Returns:
            A hozzáadott chunkok száma.
        """
        if not chunks:
            return 0

        self._ensure_init()

        # 1. Embeddings batch (a sentence-transformers natívan batch-eli)
        texts = [c["text"] for c in chunks]
        embeddings = await asyncio.to_thread(self._embeddings.embed_documents, texts)

        # 2. ChromaDB upsert
        ids = [f"{c['metadata'].get('source', 'unknown')}_{c['metadata'].get('chunk_index', i)}_{uuid.uuid4().hex[:6]}"
               for i, c in enumerate(chunks)]
        metadatas = [c["metadata"] for c in chunks]

        await asyncio.to_thread(
            self._collection.upsert,
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

        # 3. BM25 rebuild (kritikus szakasz a párhuzamos add_chunks hívások ellen)
        async with self._bm25_lock:
            for c in chunks:
                self._bm25_corpus.append(self._tokenize(c["text"]))
                self._bm25_meta.append({
                    "text": c["text"],
                    "metadata": c["metadata"],
                })
            self._bm25 = BM25Okapi(self._bm25_corpus) if self._bm25_corpus else None

        return len(chunks)

    # ------------------------------------------------------------------
    # Search — vektor + BM25 RRF fusion
    # ------------------------------------------------------------------

    async def search_hybrid(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[dict]:
        """Hibrid keresés: vektor + BM25 + RRF fusion.

        Returns:
            top_k találat: [{"text": str, "metadata": dict, "score": float, "vector_rank": int|None,
                           "bm25_rank": int|None}, ...]
        """
        self._ensure_init()

        # Vektor-keresés
        query_emb = await asyncio.to_thread(self._embeddings.embed_query, query)
        n_candidates = min(top_k * 2, 50)  # 2x top_k kandidát mindkét oldalról
        vector_result = await asyncio.to_thread(
            self._collection.query,
            query_embeddings=[query_emb],
            n_results=n_candidates,
        )

        # Az eredményt egységesítjük: id alapú dict
        # ChromaDB query result schema: {ids, documents, metadatas, distances}
        vector_hits: dict[str, dict] = {}
        if vector_result and vector_result.get("ids"):
            for rank, (id_, doc, meta, dist) in enumerate(
                zip(
                    vector_result["ids"][0],
                    vector_result["documents"][0],
                    vector_result["metadatas"][0],
                    vector_result["distances"][0],
                    strict=False,
                )
            ):
                vector_hits[id_] = {
                    "text": doc,
                    "metadata": meta,
                    "vector_rank": rank,
                    "vector_distance": dist,
                }

        # BM25 keresés (in-memory)
        bm25_hits: dict[str, dict] = {}
        async with self._bm25_lock:
            if self._bm25 is not None:
                query_tokens = self._tokenize(query)
                if query_tokens:
                    scores = self._bm25.get_scores(query_tokens)
                    # Top-N indexek score szerint
                    indexed = sorted(enumerate(scores), key=lambda x: -x[1])[:n_candidates]
                    for rank, (idx, score) in enumerate(indexed):
                        if score <= 0:
                            continue
                        meta_entry = self._bm25_meta[idx]
                        # Egységes ID: source + chunk_index (nem ChromaDB ID, de azonosító)
                        m = meta_entry["metadata"]
                        id_ = f"{m.get('source', 'unknown')}_{m.get('chunk_index', idx)}"
                        bm25_hits[id_] = {
                            "text": meta_entry["text"],
                            "metadata": m,
                            "bm25_rank": rank,
                            "bm25_score": float(score),
                        }

        # RRF fusion
        # Az ID-kulcsok különbözhetnek a két oldalon (ChromaDB UUID-suffix vs BM25 source+idx),
        # ezért text-alapú keys-szel mergelünk: az első 200 karakter mint kulcs.
        # Ez OK, mert a chunkok max 15K char hosszúak és a kezdés általában egyedi.
        text_key_to_hit: dict[str, dict] = {}
        for id_, h in vector_hits.items():
            key = h["text"][:200]
            entry = text_key_to_hit.setdefault(key, {
                "text": h["text"],
                "metadata": h["metadata"],
                "vector_rank": None,
                "bm25_rank": None,
            })
            entry["vector_rank"] = h["vector_rank"]
        for id_, h in bm25_hits.items():
            key = h["text"][:200]
            entry = text_key_to_hit.setdefault(key, {
                "text": h["text"],
                "metadata": h["metadata"],
                "vector_rank": None,
                "bm25_rank": None,
            })
            entry["bm25_rank"] = h["bm25_rank"]

        # RRF score: 1 / (k + rank + 1) -- a két rangsorból összegezzük
        for entry in text_key_to_hit.values():
            score = 0.0
            if entry["vector_rank"] is not None:
                score += 1.0 / (RRF_K + entry["vector_rank"] + 1)
            if entry["bm25_rank"] is not None:
                score += 1.0 / (RRF_K + entry["bm25_rank"] + 1)
            entry["score"] = score

        # Top-K sorted by RRF score
        sorted_hits = sorted(text_key_to_hit.values(), key=lambda x: -x["score"])
        return sorted_hits[:top_k]

    # ------------------------------------------------------------------
    # Reset (chat tab "törlés" gombhoz, eval reproducibility)
    # ------------------------------------------------------------------

    async def clear(self) -> None:
        """Az összes chunk-ot törli a Chroma + BM25 indexből.

        A persistent Chroma DB fájlban marad — csak a collection üres.
        """
        self._ensure_init()
        # ChromaDB: töröljük és újra-create-eljük a collection-t
        self._client.delete_collection(self.collection_name)  # type: ignore[union-attr]
        self._collection = self._client.get_or_create_collection(  # type: ignore[union-attr]
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        # BM25 reset
        async with self._bm25_lock:
            self._bm25_corpus = []
            self._bm25_meta = []
            self._bm25 = None

    @property
    def chunk_count(self) -> int:
        """Az indexelt chunkok száma (BM25 tükre)."""
        return len(self._bm25_meta)
