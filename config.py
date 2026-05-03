"""Central configuration — Pydantic BaseSettings env-bound.

Single source of truth: the ``settings = Settings()`` singleton. Every module
imports this. The ``.env`` file is automatically loaded (python-dotenv) if it
exists in the project root.

Profiles:
  * ``LLM_PROFILE=vllm``    — Qwen 2.5 on AMD MI300X via vLLM (OpenAI-compat). Production default.
  * ``LLM_PROFILE=ollama``  — local Ollama (Qwen 2.5 7B Instruct). Dev / data-privacy.
  * ``LLM_PROFILE=dummy``   — deterministic stub (CI / eval / load).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root absolute path — independent of where we are launched from
PROJECT_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Full application runtime configuration.

    Every field reads from .env or env vars, with defaults. If .env does not
    exist, the defaults run.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # don't raise on unknown env vars (e.g. LANGCHAIN_*)
    )

    # ---------------------------------------------------------------------
    # LLM provider selection
    # ---------------------------------------------------------------------
    llm_profile: Literal["vllm", "ollama", "dummy"] = "vllm"
    """Default LLM profile. Runtime override:
    ``graph.invoke(state, config={"configurable": {"llm_profile": "dummy"}})``."""

    # vLLM (AMD Developer Cloud MI300X) — production default
    vllm_base_url: str = "http://localhost:8000/v1"
    """vLLM endpoint URL. In production: http://<mi300x-public-ip>:8000/v1"""

    vllm_model: str = "Qwen/Qwen2.5-14B-Instruct"
    """Model id served by vLLM. Alternatives: Qwen/Qwen2.5-32B-Instruct, Qwen/Qwen2.5-7B-Instruct."""

    vllm_api_key: str | None = None
    """Optional API key for vLLM. If unset, sent as 'EMPTY' (vLLM no-auth mode).
    In production set a real key and start vLLM with --api-key <key>."""

    vllm_temperature: float = 0.0
    vllm_max_tokens: int = 4096

    # Ollama — local fallback
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    ollama_temperature: float = 0.0

    # ---------------------------------------------------------------------
    # Embedding model — sentence-transformers, runs locally on CPU
    # ---------------------------------------------------------------------
    embedding_model: str = "BAAI/bge-m3"
    """Default: BAAI/bge-m3 (2.27 GB, 1024 dim, multilingual EN/HU/DE/FR/...).
    Lighter alternative if memory-constrained: BAAI/bge-small-en-v1.5 (133 MB, 384 dim, en-only)."""

    # ---------------------------------------------------------------------
    # Storage
    # ---------------------------------------------------------------------
    chroma_path: Path = Field(default=PROJECT_ROOT / "chroma_db")
    chroma_collection: str = "documents"
    checkpoint_db_path: Path = Field(default=PROJECT_ROOT / "data" / "checkpoints.sqlite")

    # ---------------------------------------------------------------------
    # Pipeline tuning
    # ---------------------------------------------------------------------
    chunk_max_chars: int = 15_000
    chunk_overlap_chars: int = 500
    single_call_threshold: int = 30_000
    """If doc.full_text < this many chars, a single LLM call is enough (no chunking)."""

    # Loop guards
    chat_max_iterations: int = 10
    """Chat agent ↔ tools loop max iterations — infinite-loop guard."""

    validator_max_retries: int = 2
    """Chat validator → agent retry count when source citations are missing."""

    dd_supervisor_max_iterations: int = 4
    """DD supervisor max iterations before forced synthesizer fallback."""

    # ---------------------------------------------------------------------
    # Streamlit
    # ---------------------------------------------------------------------
    streamlit_port: int = 8501

    # ---------------------------------------------------------------------
    # LangSmith observability (optional)
    # ---------------------------------------------------------------------
    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None
    langchain_project: str = "document-intelligence-amd"

    # ---------------------------------------------------------------------
    # Computed fields
    # ---------------------------------------------------------------------
    @computed_field
    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @computed_field
    @property
    def langsmith_enabled(self) -> bool:
        return self.langchain_tracing_v2 and bool(self.langchain_api_key)

    @computed_field
    @property
    def is_dummy(self) -> bool:
        return self.llm_profile == "dummy"


# Singleton — every module imports this
settings = Settings()
