"""LLM adapters. Provider SDKs are optional extras."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from overseer.adapters.base import Completion, LLMAdapter, Message, Usage
from overseer.adapters.mock import MockAdapter

if TYPE_CHECKING:
    from overseer.adapters.openai import OpenAIAdapter

__all__ = [
    "Completion",
    "LLMAdapter",
    "Message",
    "MockAdapter",
    "Usage",
    "groq",
    "ollama",
    "openai_compatible",
]


def _lazy_anthropic():
    from overseer.adapters.anthropic import AnthropicAdapter

    return AnthropicAdapter


def _lazy_openai():
    from overseer.adapters.openai import OpenAIAdapter

    return OpenAIAdapter


def __getattr__(name: str):
    if name == "AnthropicAdapter":
        return _lazy_anthropic()
    if name == "OpenAIAdapter":
        return _lazy_openai()
    raise AttributeError(f"module 'overseer.adapters' has no attribute {name!r}")


def openai_compatible(
    *,
    base_url: str,
    model: str,
    api_key: str | None = None,
    timeout: float | None = None,
    extra_headers: dict[str, str] | None = None,
) -> OpenAIAdapter:
    """Point the OpenAI client at any OpenAI-compatible endpoint.

    Works with Ollama, vLLM, LM Studio, OpenRouter, Anyscale, Fireworks, etc.

        from overseer.adapters import openai_compatible

        llm = openai_compatible(
            base_url="http://localhost:11434/v1",
            model="llama3.2",
        )

    `api_key` may be omitted for endpoints that don't require auth.
    """
    from overseer.adapters.openai import OpenAIAdapter

    return OpenAIAdapter(
        api_key=api_key,
        default_model=model,
        base_url=base_url,
        timeout=timeout,
        extra_headers=extra_headers,
    )


def ollama(
    model: str,
    *,
    host: str = "http://localhost:11434",
    api_key: str | None = None,
) -> OpenAIAdapter:
    """Preset for Ollama's OpenAI-compatible endpoint.

        from overseer.adapters import ollama

        llm = ollama("llama3.2")
        llm = ollama("qwen2.5:7b", host="http://gpu-box:11434")
    """
    return openai_compatible(
        base_url=f"{host.rstrip('/')}/v1",
        model=model,
        api_key=api_key or "ollama",
    )


def groq(
    model: str,
    *,
    api_key: str | None = None,
) -> OpenAIAdapter:
    """Preset for Groq's OpenAI-compatible endpoint.

        from overseer.adapters import groq

        llm = groq("llama-3.3-70b-versatile")

    Reads `GROQ_API_KEY` from the environment if `api_key` is not provided.
    """
    return openai_compatible(
        base_url="https://api.groq.com/openai/v1",
        model=model,
        api_key=api_key or os.environ.get("GROQ_API_KEY"),
    )
