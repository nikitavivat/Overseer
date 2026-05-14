"""Shared contracts. Pydantic models that cross node and runtime boundaries."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["pass", "fail", "retry", "escalate"]


class VerifierResult(BaseModel):
    """Output of a Verifier node.

    The runtime routes edges by `verdict`. `score`, `reasons`, and
    `suggested_fix` are surfaced in the UI and in retry context.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    score: float | None = None
    reasons: list[str] = Field(default_factory=list)
    suggested_fix: dict[str, Any] | None = None


class NodeContext(BaseModel):
    """Mutable execution context passed to every node call.

    `state` carries outputs of prior nodes keyed by node name. `overrides`
    carry user interventions (e.g. an alternate prompt) applied to this call.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    node_id: str
    attempt: int = 1
    state: dict[str, Any] = Field(default_factory=dict)
    overrides: dict[str, Any] = Field(default_factory=dict)
    last_verifier: VerifierResult | None = None
