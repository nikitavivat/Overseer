"""Deterministic function node — wrap any callable as a graph node."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, ClassVar

from overseer.core.contracts import NodeContext
from overseer.nodes.base import Node


class Function(Node):
    """Wrap a plain callable as a node.

    Supported signatures (parameters matched by name):
      * `(state)` — LangGraph-style; receives the full state dict.
      * `(state, ctx)` — same, with execution context.
      * `(inputs, ctx)` / `(inputs)` — Overseer-classic; `inputs` carries
        `{"inputs": <initial>, "state": <prior outputs>}`.
      * `()` — no arguments.

    Return value:
      * `dict` — keys are merged into top-level state (LangGraph parity).
      * anything else — stored as-is under `state[node_name]`.
    """

    kind: ClassVar[str] = "function"
    idempotent: ClassVar[bool] = True

    def __init__(self, fn: Callable[..., Any], name: str | None = None) -> None:
        super().__init__(name or fn.__name__)
        self._fn = fn
        self._sig = inspect.signature(fn)

    def run(self, inputs: dict[str, Any], ctx: NodeContext) -> Any:
        params = self._sig.parameters
        if not params:
            return self._fn()

        kwargs: dict[str, Any] = {}
        if "state" in params:
            kwargs["state"] = ctx.state
        if "ctx" in params:
            kwargs["ctx"] = ctx
        if "inputs" in params:
            kwargs["inputs"] = inputs

        # If the callable takes a single positional parameter and we haven't
        # already bound a kwarg for it, pass the full state — the common
        # LangGraph idiom is `def fn(state): ...` with any parameter name.
        positional = [
            p
            for p in params.values()
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if not kwargs and len(positional) == 1:
            return self._fn(ctx.state)

        return self._fn(**kwargs)
