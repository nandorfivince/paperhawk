"""Ollama chat-model builder — local fallback.

Uses the ``langchain-ollama`` ChatOllama adapter:
  * supports ``bind_tools()`` (Ollama function calling)
  * supports streaming
  * runs locally, no API key required (offline / data-privacy use case)

Default model: Qwen 2.5 7B Instruct — reasonable quality on a laptop CPU/GPU.
For higher quality, pull qwen2.5:14b-instruct (28 GB, GPU recommended).
"""

from __future__ import annotations

from langchain_ollama import ChatOllama

from config import settings


def build_ollama_chat() -> ChatOllama:
    """ChatOllama instance from env settings.

    No API key required. If the Ollama server is not running at the
    configured URL, the first invocation fails fast with a ConnectionError.
    """
    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        temperature=settings.ollama_temperature,
    )
