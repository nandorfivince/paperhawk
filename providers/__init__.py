"""LLM provider factory — runtime injection via configurable_alternatives.

Usage::

    from providers import get_chat_model

    # Default profile (env: LLM_PROFILE)
    llm = get_chat_model()

    # Explicit profile selection
    llm = get_chat_model("dummy")

    # Runtime override inside a graph:
    graph.invoke(state, config={"configurable": {"llm_profile": "ollama"}})

The configurable_alternatives pattern lets you switch the provider at runtime
after the graph is compiled — no restart required.

The 3 profiles:
  * ``vllm``   — Qwen 2.5 served by vLLM on AMD MI300X (OpenAI-compatible API). Production default.
  * ``ollama`` — local fallback (Qwen 2.5 7B Instruct via Ollama). Dev / data-privacy.
  * ``dummy``  — deterministic stub (CI / eval / load tests). No network calls.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import ConfigurableField, Runnable

from config import settings
from providers.dummy_provider import DummyChatModel, build_dummy_chat


# Cached singleton — same configurable instance returned every time
_chat_model: Runnable | None = None
_embeddings = None  # lazy: SentenceTransformerEmbeddings | None


def get_chat_model(
    profile: Literal["vllm", "ollama", "dummy"] | None = None,
) -> Runnable:
    """Return the application chat-model. Profile selectable at runtime.

    If ``profile=None`` (default): uses ``settings.llm_profile``.

    Returns a Runnable that can switch providers at runtime via
    ``configurable_alternatives``. All three BaseChatModel implementations
    support ``bind_tools()`` and ``with_structured_output()``.
    """
    global _chat_model
    if _chat_model is None:
        env_profile = settings.llm_profile
        base = _build_base_chat(env_profile)
        # configurable_alternatives offers the other 2 profiles besides the default,
        # BUT only if the underlying package can be imported. If e.g.
        # langchain-openai is not installed (CI dummy-only run), the vllm
        # alternative is skipped — runtime switching to it would then fail-fast
        # with a single ImportError.
        alternatives: dict[str, BaseChatModel] = {}
        for alt_profile in ("vllm", "ollama", "dummy"):
            if alt_profile == env_profile:
                continue
            try:
                alternatives[alt_profile] = _build_base_chat(alt_profile)
            except (ImportError, ModuleNotFoundError):
                # Provider package is not installed — that's OK, just no swap available
                continue
        _chat_model = base.configurable_alternatives(
            ConfigurableField(id="llm_profile"),
            default_key=env_profile,
            **alternatives,
        )

    if profile is None or profile == settings.llm_profile:
        return _chat_model

    # Explicit profile selection: via Runnable.with_config
    return _chat_model.with_config({"configurable": {"llm_profile": profile}})


def _build_base_chat(profile: str) -> BaseChatModel:
    """Build a BaseChatModel for a single profile.

    The vllm/ollama providers are lazy-imported so dummy-only runs do not
    require ``langchain-openai`` or ``langchain-ollama`` to be installed
    (CI-friendly).
    """
    if profile == "dummy":
        return build_dummy_chat()
    if profile == "vllm":
        from providers.vllm_provider import build_vllm_chat
        return build_vllm_chat()
    if profile == "ollama":
        from providers.ollama_provider import build_ollama_chat
        return build_ollama_chat()
    raise ValueError(
        f"Unknown LLM profile: {profile!r}. Available: vllm|ollama|dummy"
    )


def get_embeddings():
    """Embedding model singleton (sentence-transformers, local).

    Lazy-imported: the sentence-transformers package is only loaded when
    embeddings are actually needed (Phase 3+). Phase 1 smoke tests do not
    require it, so the lazy import protects CI/dummy-only runs.
    """
    global _embeddings
    if _embeddings is None:
        from providers.embeddings import build_embeddings
        _embeddings = build_embeddings()
    return _embeddings


def get_dummy_handle() -> DummyChatModel:
    """Return a direct handle to the dummy provider (for state management).

    The UI calls ``set_docs_hint(filenames)``: after upload, the dummy reads
    the actual file list to choose tool parameters. Returns a fresh
    DummyChatModel instance because the configurable_alternatives Runnable's
    inner state is not exposed via the public API. The UI must set the
    docs_hint on the SINGLETON instance (not on this returned handle) right
    before invoking the graph — the LangGraph compile holds the singleton.

    See ``app/main.py`` session-init for the correct pattern.
    """
    return build_dummy_chat()


__all__ = [
    "get_chat_model",
    "get_embeddings",
    "get_dummy_handle",
    "DummyChatModel",
]
