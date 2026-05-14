"""Decorator + invoke/stream API parity with LangGraph-style usage."""

from __future__ import annotations

import pytest

from overseer import Process, VerifierResult
from overseer.core.graph import BlockedError


def test_node_decorator_auto_wraps_function():
    p = Process("p")

    @p.node(start=True)
    def planner(state):
        return {"plan": f"plan for {state['task']}"}

    @p.node
    def worker(state):
        return {"report": f"draft from: {state['plan']}"}

    p.connect("planner", "worker").finish("worker")
    final = p.invoke({"task": "X"})

    assert final["plan"] == "plan for X"
    assert final["report"] == "draft from: plan for X"
    assert final["planner"] == {"plan": "plan for X"}  # state[node_name] kept for back-compat


def test_node_decorator_with_explicit_name():
    p = Process("p")

    @p.node(name="Planner", start=True)
    def _do_plan(state):
        return "plan"

    p.finish("Planner")
    final = p.invoke({})
    assert final["Planner"] == "plan"


def test_scalar_return_is_stored_under_node_name():
    p = Process("p")

    @p.node(start=True)
    def echo(state):
        return state["msg"]

    p.finish("echo")
    final = p.invoke({"msg": "hi"})
    assert final["echo"] == "hi"


def test_verifier_decorator_autowires():
    p = Process("p")

    @p.node(start=True)
    def write(state):
        return {"report": state.get("__overrides__", {}).get("report", "weak draft")}

    @p.verifier(after="write", retry=2)
    def critic(state) -> VerifierResult:
        if "evidence" in state.get("report", "").lower():
            return VerifierResult(verdict="pass")
        return VerifierResult(verdict="fail", reasons=["no evidence"])

    # Verify auto-wired edges.
    edges = {(e.source, e.target, e.condition) for e in p.edges}
    assert ("write", "critic", None) in edges
    assert ("critic", "write", "fail") in edges
    assert ("critic", "end", "pass") in edges


def test_stream_yields_events_in_order():
    p = Process("p")

    @p.node(start=True)
    def one(state):
        return {"x": 1}

    @p.node
    def two(state):
        return {"y": state["x"] + 1}

    p.connect("one", "two").finish("two")
    events = list(p.stream({}))
    types = [e.type for e in events]

    assert types[0] == "run_started"
    assert types[-1] == "run_completed"
    assert "node_completed" in types
    assert types.count("node_completed") == 2


def test_invoke_returns_final_state_with_inputs_spread():
    p = Process("p")

    @p.node(start=True)
    def passthrough(state):
        return {"echoed": state["task"]}

    p.finish("passthrough")
    final = p.invoke({"task": "hello"})
    assert final["task"] == "hello"  # initial inputs spread to top level
    assert final["__inputs__"] == {"task": "hello"}  # also kept explicit
    assert final["echoed"] == "hello"


def test_verifier_must_return_verifier_result(tmp_path):
    """A verifier that returns the wrong type is treated as a node failure;
    `invoke()` aborts and raises BlockedError. The original TypeError is
    surfaced via the node_failed event payload."""
    from overseer.persistence.store import Store

    p = Process("p")

    @p.node(start=True)
    def w(state):
        return "x"

    @p.verifier(after="w")
    def bad(state):
        return "not a verifier result"

    store = Store(tmp_path / "t.db")
    with pytest.raises(BlockedError):
        p.invoke({}, store=store)

    failures = [
        e for e in store.list_events(store.list_runs()[0]["run_id"])
        if e["type"] == "node_failed"
    ]
    assert failures
    assert "VerifierResult" in failures[0]["payload"]["error"]
