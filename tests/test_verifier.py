"""Verifier-result routing."""

from __future__ import annotations

import pytest

from overseer import NodeContext, Process, Verifier, VerifierResult
from overseer.adapters import MockAdapter
from overseer.core.runtime import RunStatus, Runtime
from overseer.nodes.agent import Agent
from overseer.persistence.store import Store


class _Echo(Agent):
    model = "mock"

    def prompt(self, inputs, ctx):
        return "anything"


class _PassIfContainsX(Verifier):
    def verify(self, ctx: NodeContext) -> VerifierResult:
        output = str(ctx.state.get("Echo", ""))
        if "x" in output:
            return VerifierResult(verdict="pass", score=1.0)
        return VerifierResult(verdict="fail", score=0.0, reasons=["missing x"])


@pytest.fixture
def store_factory(tmp_path):
    def _make(name="t.db") -> Store:
        return Store(tmp_path / name)
    return _make


def test_pass_routes_to_end(store_factory):
    store = store_factory()
    runtime = Runtime(store=store)
    adapter = MockAdapter(["xyz"])

    p = Process("p")
    p.add_node("Echo", _Echo(adapter), start=True)
    p.add_node("Check", _PassIfContainsX())
    p.connect("Echo", "Check")
    p.connect("Check", "end", condition="pass")
    p.connect("Check", "Echo", condition="fail")

    result = runtime.run(p, inputs={})
    assert result.status is RunStatus.COMPLETED
    assert result.state["Check"]["verdict"] == "pass"


def test_verifier_result_schema_rejects_unknown_verdict():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VerifierResult(verdict="maybe")  # type: ignore[arg-type]


def test_verifier_result_serializes_round_trip():
    r = VerifierResult(verdict="fail", score=0.3, reasons=["a", "b"])
    dumped = r.model_dump()
    assert dumped["verdict"] == "fail"
    assert dumped["reasons"] == ["a", "b"]
    assert VerifierResult(**dumped) == r
