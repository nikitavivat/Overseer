"""Edge-level policies that govern what runtime does on verifier outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Retry:
    """Retry the source side of the edge up to `max` times."""

    max: int = 3
    with_critic: str | None = None


@dataclass(frozen=True)
class Halt:
    """Stop the run. UI must intervene to continue."""

    notify: str | None = None


PolicyAction = Retry | Halt


@dataclass(frozen=True)
class Policy:
    """Maps verifier verdicts to actions.

    Attached to an edge. Inspected by the runtime when traversing that edge.
    """

    on_fail: PolicyAction | None = None
    on_escalate: PolicyAction | None = field(default_factory=lambda: Halt())
    on_retry: PolicyAction | None = None
