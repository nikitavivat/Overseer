"""Synchronous executor that walks a Process, snapshots state, and emits events.

Designed to be pausable: when a verifier exhausts its retry budget, the
runtime blocks on a per-run control queue until the UI submits an
intervention (retry-with-override / skip / abort).
"""

from __future__ import annotations

import logging
import queue
import time
import traceback
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from overseer.core.contracts import NodeContext, VerifierResult
from overseer.core.events import Event, EventBus, EventTypes
from overseer.core.graph import TERMINAL, Edge, Process
from overseer.persistence.store import Store
from overseer.quality.policies import Halt, Retry

log = logging.getLogger(__name__)


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass
class RunResult:
    run_id: str
    status: RunStatus
    state: dict[str, Any]
    blocked_node: str | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None


@dataclass
class Intervention:
    """Message from the control plane to a blocked run."""

    action: str  # "retry", "skip", "abort"
    node: str | None = None
    overrides: dict[str, Any] = field(default_factory=dict)


class Runtime:
    """Owns event bus + store + active control queues. One instance per app."""

    def __init__(self, store: Store, bus: EventBus | None = None) -> None:
        self.store = store
        self.bus = bus or EventBus()
        self.bus.on_any(self._persist_event)
        self._control: dict[str, queue.Queue[Intervention]] = {}
        self._results: dict[str, RunResult] = {}

    # ---------- public API ----------

    def run(
        self,
        process: Process,
        inputs: dict[str, Any] | None = None,
        *,
        run_id: str | None = None,
    ) -> RunResult:
        validation = process.validate()
        if not validation.ok:
            raise ValueError("Graph is invalid: " + "; ".join(validation.errors))
        for warning in validation.warnings:
            log.warning("graph: %s", warning)

        run_id = run_id or str(uuid.uuid4())
        self._control[run_id] = queue.Queue()
        self.store.record_run(run_id=run_id, process_name=process.name)

        # Hybrid state: initial inputs are spread at the top level so nodes
        # can read `state["task"]` directly (LangGraph-style). The full input
        # dict is also preserved under `__inputs__` for explicit access.
        initial = dict(inputs or {})
        state: dict[str, Any] = {"__inputs__": initial, **initial}
        result = RunResult(run_id=run_id, status=RunStatus.RUNNING, state=state)
        self._results[run_id] = result

        self.bus.emit(
            Event(run_id=run_id, type=EventTypes.RUN_STARTED, payload={"process": process.name})
        )

        try:
            self._execute(process, run_id, state, result)
        except Exception as exc:
            result.status = RunStatus.FAILED
            result.error = f"{type(exc).__name__}: {exc}"
            result.ended_at = time.time()
            self.bus.emit(
                Event(
                    run_id=run_id,
                    type=EventTypes.RUN_FAILED,
                    payload={"error": result.error, "trace": traceback.format_exc()},
                )
            )
            self.store.update_run(run_id, status=result.status.value, ended_at=result.ended_at)
            raise
        finally:
            self._control.pop(run_id, None)

        return result

    def submit(self, run_id: str, intervention: Intervention) -> None:
        """Deliver a control message to a blocked run."""
        if run_id not in self._control:
            raise KeyError(f"No active run {run_id!r}")
        self._control[run_id].put(intervention)
        self.bus.emit(
            Event(
                run_id=run_id,
                type=EventTypes.USER_INTERVENTION,
                node_id=intervention.node,
                payload={"action": intervention.action, "overrides": intervention.overrides},
            )
        )

    def get_result(self, run_id: str) -> RunResult | None:
        return self._results.get(run_id)

    # ---------- internals ----------

    def _execute(
        self,
        process: Process,
        run_id: str,
        state: dict[str, Any],
        result: RunResult,
    ) -> None:
        current: str | None = process.start_node
        # Per-target retry counters, scoped to the inbound edge that triggered the retry.
        retries: dict[tuple[str, str], int] = {}
        overrides: dict[str, Any] = {}

        while current is not None and current != TERMINAL:
            node = process.nodes[current]
            attempt = retries.get((current, current), 0) + 1
            ctx = NodeContext(
                run_id=run_id,
                node_id=current,
                attempt=attempt,
                state=state,
                overrides=dict(overrides),
                last_verifier=_extract_last_verifier(state),
            )

            snapshot_id = self.store.put_snapshot(
                run_id=run_id,
                node_id=current,
                data={
                    "inputs": state.get("__inputs__", {}),
                    "state": _safe_copy(state),
                    "overrides": overrides,
                    "attempt": attempt,
                },
            )
            self.bus.emit(
                Event(
                    run_id=run_id,
                    node_id=current,
                    type=EventTypes.NODE_STARTED,
                    payload={"snapshot_id": snapshot_id, "attempt": attempt},
                )
            )

            output, failure = self._invoke_node(node, ctx, run_id)
            if failure is not None:
                self.bus.emit(
                    Event(
                        run_id=run_id,
                        node_id=current,
                        type=EventTypes.NODE_FAILED,
                        payload={"error": failure},
                    )
                )
                next_node = self._await_intervention(run_id, current, result, overrides)
                if next_node is None:
                    return
                current = next_node
                continue

            state[current] = _serialize_output(output)
            merged_keys = _merge_dict_output_into_state(node, output, state)
            self.bus.emit(
                Event(
                    run_id=run_id,
                    node_id=current,
                    type=EventTypes.NODE_COMPLETED,
                    payload={
                        "output": state[current],
                        "merged_keys": merged_keys,
                    },
                )
            )

            if isinstance(output, VerifierResult):
                self.bus.emit(
                    Event(
                        run_id=run_id,
                        node_id=current,
                        type=f"verifier_{output.verdict}",
                        payload={"score": output.score, "reasons": output.reasons},
                    )
                )

            edge = self._select_edge(process.outgoing(current), output)
            if edge is None:
                # No matching edge — treat as blocked, ask for intervention.
                self.bus.emit(
                    Event(
                        run_id=run_id,
                        node_id=current,
                        type=EventTypes.NODE_BLOCKED,
                        payload={"reason": "no edge matched"},
                    )
                )
                next_node = self._await_intervention(run_id, current, result, overrides)
                if next_node is None:
                    return
                current = next_node
                continue

            should_retry, retry_overrides = self._apply_policy(
                edge, output, retries, run_id, current
            )
            if should_retry:
                overrides = retry_overrides
                current = edge.target
                continue

            if isinstance(edge.policy and edge.policy.on_fail, Halt) and _is_fail(output):
                next_node = self._await_intervention(run_id, current, result, overrides)
                if next_node is None:
                    return
                current = next_node
                continue

            if _is_fail(output) and edge.policy and isinstance(edge.policy.on_fail, Retry):
                # Retry budget exhausted. Block on the retry *target* (the
                # node the user would naturally fix), not the verifier — the
                # UI drawer lands where intervention makes sense.
                retry_target = edge.target
                self.bus.emit(
                    Event(
                        run_id=run_id,
                        node_id=retry_target,
                        type=EventTypes.NODE_BLOCKED,
                        payload={
                            "reason": "retry budget exhausted",
                            "max": edge.policy.on_fail.max,
                            "verifier": current,
                        },
                    )
                )
                next_node = self._await_intervention(run_id, retry_target, result, overrides)
                if next_node is None:
                    return
                current = next_node
                continue

            overrides = {}
            current = edge.target

        result.status = RunStatus.COMPLETED
        result.ended_at = time.time()
        self.bus.emit(
            Event(run_id=run_id, type=EventTypes.RUN_COMPLETED, payload={"state": state})
        )
        self.store.update_run(run_id, status=result.status.value, ended_at=result.ended_at)

    def _invoke_node(
        self, node: Any, ctx: NodeContext, run_id: str
    ) -> tuple[Any, str | None]:
        try:
            inputs = _collect_inputs(ctx)
            return node.run(inputs, ctx), None
        except Exception as exc:
            log.exception("Node %s raised", ctx.node_id)
            return None, f"{type(exc).__name__}: {exc}"

    def _select_edge(self, edges: Iterable[Edge], output: Any) -> Edge | None:
        edges = list(edges)
        fallback: Edge | None = None
        for edge in edges:
            if edge.condition is None:
                fallback = fallback or edge
                continue
            if _matches(edge.condition, output):
                return edge
        return fallback

    def _apply_policy(
        self,
        edge: Edge,
        output: Any,
        retries: dict[tuple[str, str], int],
        run_id: str,
        current: str,
    ) -> tuple[bool, dict[str, Any]]:
        if edge.policy is None:
            return False, {}
        action = edge.policy.on_fail if _is_fail(output) else None
        if action is None:
            return False, {}
        if isinstance(action, Retry):
            key = (edge.source, edge.target)
            count = retries.get(key, 0) + 1
            if count <= action.max:
                retries[key] = count
                self.bus.emit(
                    Event(
                        run_id=run_id,
                        node_id=current,
                        type=EventTypes.VERIFIER_RETRY,
                        payload={"attempt": count, "max": action.max},
                    )
                )
                overrides = _retry_overrides(output, action)
                return True, overrides
        return False, {}

    def _await_intervention(
        self,
        run_id: str,
        node_id: str,
        result: RunResult,
        overrides: dict[str, Any],
    ) -> str | None:
        result.status = RunStatus.BLOCKED
        result.blocked_node = node_id
        self.bus.emit(
            Event(
                run_id=run_id,
                node_id=node_id,
                type=EventTypes.RUN_BLOCKED,
                payload={"blocked_node": node_id},
            )
        )
        self.store.update_run(run_id, status=result.status.value)
        msg = self._control[run_id].get()
        result.status = RunStatus.RUNNING
        result.blocked_node = None
        self.store.update_run(run_id, status=result.status.value)
        self.bus.emit(
            Event(
                run_id=run_id,
                node_id=node_id,
                type=EventTypes.RUN_RESUMED,
                payload={"action": msg.action},
            )
        )

        if msg.action == "abort":
            result.status = RunStatus.ABORTED
            result.ended_at = time.time()
            self.store.update_run(run_id, status=result.status.value, ended_at=result.ended_at)
            return None
        if msg.action == "skip":
            return TERMINAL
        # "retry" (or anything else treated as retry): replay the same node
        # with user-supplied overrides applied to the next invocation.
        overrides.clear()
        overrides.update(msg.overrides)
        return msg.node or node_id

    def _persist_event(self, event: Event) -> None:
        try:
            self.store.append_event(event)
        except Exception:
            log.exception("Failed to persist event %s", event.event_id)


# ---------- helpers ----------

def _is_fail(output: Any) -> bool:
    return isinstance(output, VerifierResult) and output.verdict == "fail"


def _matches(condition: Any, output: Any) -> bool:
    if isinstance(condition, str):
        if isinstance(output, VerifierResult):
            return output.verdict == condition
        return False
    if callable(condition):
        try:
            return bool(condition(output))
        except Exception:
            log.exception("Edge condition raised")
            return False
    return False


def _retry_overrides(output: Any, action: Retry) -> dict[str, Any]:
    """Build a retry override from a verifier result.

    Inject critic reasons into a `critic_feedback` override so Agent
    subclasses can fold them into the next prompt without extra plumbing.
    """
    overrides: dict[str, Any] = {}
    if isinstance(output, VerifierResult):
        overrides["critic_feedback"] = {
            "reasons": output.reasons,
            "score": output.score,
            "suggested_fix": output.suggested_fix,
        }
        if action.with_critic:
            overrides["critic_node"] = action.with_critic
    return overrides


def _extract_last_verifier(state: dict[str, Any]) -> VerifierResult | None:
    for value in reversed(list(state.values())):
        if isinstance(value, dict) and "verdict" in value and "reasons" in value:
            try:
                return VerifierResult(**value)
            except Exception:
                return None
    return None


def _collect_inputs(ctx: NodeContext) -> dict[str, Any]:
    """Pass the initial inputs and all prior outputs to the node."""
    return {
        "inputs": ctx.state.get("__inputs__", {}),
        "state": {k: v for k, v in ctx.state.items() if not k.startswith("__")},
    }


def _merge_dict_output_into_state(node: Any, output: Any, state: dict[str, Any]) -> list[str]:
    """If a Function node returns a dict, merge its keys into top-level state.

    Verifier and Agent outputs are kept under `state[node_name]` only — they
    are positional, not state updates.
    """
    from overseer.nodes.function import Function

    if not isinstance(node, Function):
        return []
    if not isinstance(output, dict):
        return []
    merged: list[str] = []
    for key, value in output.items():
        if key.startswith("__"):
            continue
        state[key] = _serialize_output(value)
        merged.append(key)
    return merged


def _serialize_output(value: Any) -> Any:
    if isinstance(value, VerifierResult):
        return value.model_dump()
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump()
    if isinstance(value, (str, int, float, bool, type(None), dict, list)):
        return value
    return str(value)


def _safe_copy(state: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe deep copy via serialization round-trip."""
    import json

    try:
        return json.loads(json.dumps(state, default=str))
    except Exception:
        return {k: str(v) for k, v in state.items()}
