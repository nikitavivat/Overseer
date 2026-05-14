"""OpenAI Chat Completions adapter.

Works with the official OpenAI API and with any OpenAI-compatible endpoint
(Ollama, vLLM, LM Studio, Groq, Together, OpenRouter, Anyscale, ...) by
passing `base_url`. Requires the optional `openai` extra:

    pip install overseer[openai]
"""

from __future__ import annotations

import os
from typing import Any

from overseer.adapters.base import Completion, LLMAdapter, Message, Usage


class OpenAIAdapter(LLMAdapter):
    name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "gpt-4o-mini",
        *,
        base_url: str | None = None,
        timeout: float | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "OpenAIAdapter requires the `openai` package. "
                "Install with: pip install overseer[openai]"
            ) from exc
        kwargs: dict[str, Any] = {
            "api_key": api_key or os.environ.get("OPENAI_API_KEY") or "not-needed",
        }
        if base_url is not None:
            kwargs["base_url"] = base_url
        if timeout is not None:
            kwargs["timeout"] = timeout
        if extra_headers:
            kwargs["default_headers"] = extra_headers
        self._client = OpenAI(**kwargs)
        self.default_model = default_model
        self.base_url = base_url

    def complete(
        self,
        *,
        system: str = "",
        user: str = "",
        model: str | None = None,
        messages: list[Message] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Completion:
        chat: list[dict[str, Any]] = []
        if system:
            chat.append({"role": "system", "content": system})
        if messages:
            for m in messages:
                chat.append({"role": m.role, "content": m.content})
        if not messages:
            chat.append({"role": "user", "content": user})

        kwargs: dict[str, Any] = {"model": model or self.default_model, "messages": chat}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        text = choice.message.content or ""
        usage = response.usage
        return Completion(
            text=text,
            model=response.model,
            usage=Usage(
                input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
                output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            ),
            raw=response.model_dump() if hasattr(response, "model_dump") else None,
        )
