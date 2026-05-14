"""LLM adapter interface. Concrete adapters live in sibling modules."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Completion:
    text: str
    model: str
    usage: Usage = field(default_factory=Usage)
    raw: dict | None = None


class LLMAdapter:
    """Abstract LLM client. Implementations call a single chat-style endpoint."""

    name: str = "abstract"

    def complete(
        self,
        *,
        system: str = "",
        user: str = "",
        model: str,
        messages: list[Message] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Completion:
        raise NotImplementedError
