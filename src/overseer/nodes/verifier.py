"""Verifier: a Node whose output is a VerifierResult and which routes by verdict.

A Verifier inspects `ctx.state` to find the output it verifies — the source
of truth lives in the graph (the edge that feeds it), not in any implicit
binding.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, ClassVar

from overseer.core.contracts import NodeContext, VerifierResult
from overseer.nodes.base import Node


class Verifier(Node):
    """Base class. Subclasses override `verify(ctx) -> VerifierResult`."""

    kind: ClassVar[str] = "verifier"
    idempotent: ClassVar[bool] = True

    def verify(self, ctx: NodeContext) -> VerifierResult:
        raise NotImplementedError

    def run(self, inputs: dict[str, Any], ctx: NodeContext) -> VerifierResult:
        return self.verify(ctx)


class _FunctionVerifier(Verifier):
    """Wraps a plain `(state) -> VerifierResult` function as a Verifier node."""

    def __init__(self, fn: Callable[..., VerifierResult], name: str) -> None:
        super().__init__(name=name)
        self._fn = fn
        self._sig = inspect.signature(fn)

    def verify(self, ctx: NodeContext) -> VerifierResult:
        params = self._sig.parameters
        kwargs: dict[str, Any] = {}
        if "state" in params:
            kwargs["state"] = ctx.state
        if "ctx" in params:
            kwargs["ctx"] = ctx

        if kwargs:
            result = self._fn(**kwargs)
        elif len(params) == 1:
            result = self._fn(ctx.state)
        else:
            result = self._fn()

        if not isinstance(result, VerifierResult):
            raise TypeError(
                f"Verifier {self.name!r} must return VerifierResult, "
                f"got {type(result).__name__}"
            )
        return result


def _function_verifier(fn: Callable[..., VerifierResult], name: str) -> _FunctionVerifier:
    """Factory used by `@process.verifier` to wrap a function as a node."""
    return _FunctionVerifier(fn, name)
