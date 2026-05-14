"""Agent: a Node that calls an LLM. Subclasses customize prompt/parse."""

from __future__ import annotations

from typing import Any, ClassVar

from overseer.adapters.base import LLMAdapter, Message
from overseer.core.contracts import NodeContext
from overseer.nodes.base import Node


class Agent(Node):
    """LLM-backed node.

    Override `prompt(inputs, ctx)` to build the user message and `parse(text)`
    to convert the raw response. `system` and `model` are class attributes by
    default but may be overridden via `ctx.overrides`.
    """

    kind: ClassVar[str] = "agent"
    idempotent: ClassVar[bool] = False

    model: str = ""
    system: str = ""
    temperature: float | None = None
    max_tokens: int | None = None

    def __init__(self, adapter: LLMAdapter, *, name: str | None = None) -> None:
        super().__init__(name)
        self.adapter = adapter

    def prompt(self, inputs: dict[str, Any], ctx: NodeContext) -> str:
        """Default: read `inputs["inputs"]["task"]`. Override for real flows."""
        task = inputs.get("inputs", {}).get("task")
        return str(task or "")

    def parse(self, text: str, ctx: NodeContext) -> Any:
        return text

    def run(self, inputs: dict[str, Any], ctx: NodeContext) -> Any:
        override_prompt = ctx.overrides.get("prompt")
        if override_prompt is not None:
            user_prompt = str(override_prompt)
        else:
            user_prompt = self.prompt(inputs, ctx)
            feedback = ctx.overrides.get("critic_feedback")
            if feedback:
                user_prompt = self._fold_feedback(user_prompt, feedback)

        system = ctx.overrides.get("system", self.system)
        model = ctx.overrides.get("model", self.model)
        if not model:
            raise ValueError(
                f"Agent {self.name!r} has no `model` set. Define it on the class "
                "or pass via overrides."
            )

        completion = self.adapter.complete(
            system=system,
            user=user_prompt,
            model=model,
            temperature=ctx.overrides.get("temperature", self.temperature),
            max_tokens=ctx.overrides.get("max_tokens", self.max_tokens),
            messages=[Message("user", user_prompt)],
        )
        return self.parse(completion.text, ctx)

    @staticmethod
    def _fold_feedback(prompt: str, feedback: dict) -> str:
        reasons = feedback.get("reasons") or []
        if not reasons:
            return prompt
        bullets = "\n".join(f"- {r}" for r in reasons)
        return (
            f"{prompt}\n\n"
            "The previous attempt failed quality checks for these reasons:\n"
            f"{bullets}\n"
            "Address each one in the new attempt."
        )
