"""Runtime: happy path, retry budget, user intervention."""

from __future__ import annotations

import threading
import time

from overseer import (
    Agent,
    Function,
    NodeContext,
    Policy,
    Process,
    Retry,
    Verifier,
    VerifierResult,
)
from overseer.adapters import MockAdapter
from overseer.core.runtime import Intervention, RunStatus, Runtime
from overseer.persistence.store import Store


def _doubler(inputs):
    return (inputs.get("inputs", {}).get("value", 0)) * 2


def test_runtime_executes_linear_graph(runtime: Runtime):
    p = Process("p")
    p.add_node("double", Function(_doubler))
    p.connect("double", "end")
    result = runtime.run(p, inputs={"value": 5})
    assert result.status is RunStatus.COMPLETED
    assert result.state["double"] == 10


def test_runtime_records_events(runtime: Runtime, tmp_store: Store):
    p = Process("p")
    p.add_node("a", Function(lambda inputs: "ok"))
    p.connect("a", "end")
    result = runtime.run(p, inputs={})
    events = tmp_store.list_events(result.run_id)
    types = [e["type"] for e in events]
    assert "run_started" in types
    assert "node_started" in types
    assert "node_completed" in types
    assert "run_completed" in types


class _AlwaysFail(Verifier):
    def verify(self, ctx: NodeContext) -> VerifierResult:
        return VerifierResult(verdict="fail", reasons=["nope"])


class _CountingAgent(Agent):
    model = "mock"

    def prompt(self, inputs, ctx):
        return f"call#{ctx.attempt}"


def test_retry_budget_then_block_then_intervene(tmp_store: Store):
    """After 3 fail-retries the run blocks; an intervention with an override
    resumes it. The verifier still says fail (deterministic), so the run
    re-blocks — we then abort to terminate cleanly."""

    runtime = Runtime(store=tmp_store)
    adapter = MockAdapter(["draft 1", "draft 2", "draft 3", "draft 4", "draft 5"])

    p = Process("p")
    p.add_node("Worker", _CountingAgent(adapter), start=True)
    p.add_node("Critic", _AlwaysFail())
    p.connect("Worker", "Critic")
    p.connect(
        "Critic", "Worker",
        condition="fail",
        policy=Policy(on_fail=Retry(max=3)),
    )
    p.connect("Critic", "end", condition="pass")

    blocked = threading.Event()
    runtime.bus.on("run_blocked", lambda _e: blocked.set())

    runs: dict[str, object] = {}

    def _runner():
        try:
            runs["result"] = runtime.run(p, inputs={"task": "x"})
        except Exception as exc:
            runs["error"] = exc

    thread = threading.Thread(target=_runner)
    thread.start()

    assert blocked.wait(timeout=5), "run never blocked"

    # Intervene with override: a single retry, then abort to end the test.
    runtime.submit(
        runs.get("run_id") or _first_run(tmp_store),
        Intervention(action="retry", node="Worker", overrides={"prompt": "new attempt"}),
    )
    # Wait for re-block (it will fail again since critic always fails).
    time.sleep(0.2)
    blocked.clear()
    blocked.wait(timeout=5)
    runtime.submit(_first_run(tmp_store), Intervention(action="abort"))
    thread.join(timeout=5)

    result = runs.get("result")
    assert result is not None
    assert result.status is RunStatus.ABORTED


def _first_run(store: Store) -> str:
    return store.list_runs()[0]["run_id"]


def test_critic_feedback_is_passed_via_overrides(tmp_store: Store):
    """A failing verifier's reasons surface to the agent's next prompt."""
    runtime = Runtime(store=tmp_store)
    seen_prompts: list[str] = []

    adapter = MockAdapter(
        lambda *, system, user, model: (seen_prompts.append(user) or "draft")
    )

    class W(Agent):
        model = "mock"

        def prompt(self, inputs, ctx):
            return "base prompt"

    p = Process("p")
    p.add_node("Worker", W(adapter), start=True)
    p.add_node("Critic", _AlwaysFail())
    p.connect("Worker", "Critic")
    p.connect(
        "Critic", "Worker",
        condition="fail",
        policy=Policy(on_fail=Retry(max=1)),
    )
    p.connect("Critic", "end", condition="pass")

    blocked = threading.Event()
    runtime.bus.on("run_blocked", lambda _e: blocked.set())

    import contextlib

    def _runner():
        with contextlib.suppress(Exception):
            runtime.run(p, inputs={})

    thread = threading.Thread(target=_runner)
    thread.start()
    blocked.wait(timeout=5)
    runtime.submit(_first_run(tmp_store), Intervention(action="abort"))
    thread.join(timeout=5)

    # First call has base prompt; retry call should fold in feedback.
    assert "base prompt" in seen_prompts[0]
    assert any("previous attempt failed" in p.lower() for p in seen_prompts[1:])
