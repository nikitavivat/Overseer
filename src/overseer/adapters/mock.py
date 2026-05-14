"""Mock adapter for tests and offline demos.

Either pass a list of pre-baked responses (consumed in order) or a callable
`(*, system, user, model) -> str`. The mock is fully deterministic — ideal
for replays and CI.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from overseer.adapters.base import Completion, LLMAdapter, Message, Usage

Responder = Callable[..., str]
ResponseSource = Responder | Iterable[str]


class MockAdapter(LLMAdapter):
    name = "mock"

    def __init__(self, source: ResponseSource) -> None:
        if callable(source):
            self._responder: Responder = source
            self._iter = None
        else:
            self._responder = None  # type: ignore[assignment]
            self._iter = iter(source)
        self.calls: list[dict] = []

    def complete(
        self,
        *,
        system: str = "",
        user: str = "",
        model: str = "mock",
        messages: list[Message] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Completion:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if self._responder is not None:
            text = self._responder(system=system, user=user, model=model)
        else:
            assert self._iter is not None
            try:
                text = next(self._iter)
            except StopIteration:
                text = ""
        return Completion(
            text=text,
            model=model,
            usage=Usage(input_tokens=len(user) // 4, output_tokens=len(text) // 4),
        )
