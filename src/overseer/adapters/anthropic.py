"""Anthropic Messages API adapter.

Requires the optional `anthropic` extra: `pip install overseer[anthropic]`.
"""

from __future__ import annotations

import os
from typing import Any

from overseer.adapters.base import Completion, LLMAdapter, Message, Usage


class AnthropicAdapter(LLMAdapter):
    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "claude-opus-4-7",
    ) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ImportError(
                "AnthropicAdapter requires the `anthropic` package. "
                "Install with: pip install overseer[anthropic]"
            ) from exc
        self._client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.default_model = default_model

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
        msgs: list[dict[str, Any]] = []
        if messages:
            for m in messages:
                if m.role == "system":
                    system = m.content
                else:
                    msgs.append({"role": m.role, "content": m.content})
        if not msgs:
            msgs = [{"role": "user", "content": user}]

        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": msgs,
            "max_tokens": max_tokens or 4096,
        }
        if system:
            kwargs["system"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature

        response = self._client.messages.create(**kwargs)
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        return Completion(
            text=text,
            model=response.model,
            usage=Usage(
                input_tokens=getattr(response.usage, "input_tokens", 0),
                output_tokens=getattr(response.usage, "output_tokens", 0),
            ),
            raw=response.model_dump() if hasattr(response, "model_dump") else None,
        )
