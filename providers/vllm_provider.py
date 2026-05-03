"""vLLM chat-model builder — AMD MI300X served, OpenAI-compatible API.

vLLM serves Qwen 2.5 14B Instruct (or any other compatible model) on an AMD
Instinct MI300X via the OpenAI-compatible REST API. We use `langchain-openai`'s
`ChatOpenAI` adapter with a custom `base_url` pointing at the vLLM endpoint —
NOT the OpenAI cloud.

Why ChatOpenAI:
  * vLLM exposes ``/v1/chat/completions`` in the OpenAI format
  * Tool calling works natively (Qwen 2.5 supports function calling)
  * ``with_structured_output()`` works via tool-binding
  * Streaming works via SSE

Required env vars (see ``.env.example``):
  * ``VLLM_BASE_URL`` — e.g. ``http://<mi300x-public-ip>:8000/v1``
  * ``VLLM_MODEL``    — e.g. ``Qwen/Qwen2.5-14B-Instruct``
  * ``VLLM_API_KEY``  — optional. Empty => sent as ``"EMPTY"`` (vLLM no-auth).
                       In production set a real key and start vLLM with ``--api-key``.
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from config import settings


def build_vllm_chat() -> ChatOpenAI:
    """Default ChatOpenAI instance pointed at the AMD MI300X vLLM endpoint.

    The first invocation triggers the underlying HTTP client. If the endpoint
    is unreachable, the call fails fast with a connection error — NOT here at
    construction time, so dummy/Ollama profiles need not have ``VLLM_BASE_URL``
    set.
    """
    return ChatOpenAI(
        model=settings.vllm_model,
        base_url=settings.vllm_base_url,
        api_key=settings.vllm_api_key or "EMPTY",
        temperature=settings.vllm_temperature,
        max_tokens=settings.vllm_max_tokens,
        timeout=120,
    )
