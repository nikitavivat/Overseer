"""Base Node class. Every executable unit in a Process subclasses this."""

from __future__ import annotations

from typing import Any, ClassVar

from overseer.core.contracts import NodeContext


class Node:
    """Minimal execution unit.

    Subclasses implement `run(inputs, ctx) -> output`. Outputs must be
    JSON-serializable (`dict`, `list`, `str`, `int`, `float`, `bool`, `None`)
    or expose `.model_dump()` (Pydantic models).
    """

    kind: ClassVar[str] = "node"
    idempotent: ClassVar[bool] = False

    def __init__(self, name: str | None = None) -> None:
        self.name: str = name or self.__class__.__name__

    def run(self, inputs: dict[str, Any], ctx: NodeContext) -> Any:
        raise NotImplementedError(f"{type(self).__name__}.run is not implemented")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r})"
