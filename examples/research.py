"""Research agent: Planner → Worker → Critic with retry-then-block.

Demonstrates the MVP acceptance criterion in four observable steps:

  1. Run starts; Planner and Worker execute.
  2. EvidenceCritic fails the Worker (no "evidence" in the report).
  3. Three automatic retries also fail (mock adapter is deterministic).
  4. Runtime blocks. From the UI, type an override prompt that mentions
     "evidence", click Retry, and the next Worker attempt passes.

Runs offline against a MockAdapter by default; set ANTHROPIC_API_KEY to use
the real Claude model instead.
"""

from __future__ import annotations

import os
from typing import Any

from overseer import (
    Agent,
    NodeContext,
    Policy,
    Process,
    Retry,
    Verifier,
    VerifierResult,
)
from overseer.adapters import MockAdapter
from overseer.adapters.base import LLMAdapter

UNLOCK_PHRASE = "include citations"


def _mock_responder(*, system: str, user: str, model: str) -> str:
    """Deterministic responder gated on an explicit unlock phrase.

    The Worker won't self-heal from generic critic reasons — the user must
    edit the prompt and explicitly request citations. That's the point of
    the demo: human-in-the-loop is sometimes the only way out.
    """
    if "plan how to" in user.lower():
        return (
            "Plan:\n"
            "1. Identify primary sources.\n"
            "2. Summarize findings.\n"
            "3. Cross-check claims."
        )
    if UNLOCK_PHRASE in user.lower():
        return (
            "Final report:\n"
            "Renewable adoption has accelerated. According to IEA reports (2024), "
            "solar capacity grew 32% YoY. Evidence supports the trend across all "
            "OECD members. Citations: [IEA 2024], [IRENA 2023]."
        )
    return (
        "Draft report:\n"
        "Renewables are becoming more popular. Many countries are installing more "
        "solar panels and wind turbines. The future looks bright."
    )


def build_adapter() -> LLMAdapter:
    if os.getenv("ANTHROPIC_API_KEY"):
        from overseer.adapters import AnthropicAdapter

        return AnthropicAdapter()
    return MockAdapter(_mock_responder)


adapter = build_adapter()


class Planner(Agent):
    model = "claude-opus-4-7"
    system = "You are a planner. Produce a numbered, three-step plan."

    def prompt(self, inputs: dict[str, Any], ctx: NodeContext) -> str:
        task = inputs.get("inputs", {}).get("task", "")
        return f"Plan how to: {task}"


class Worker(Agent):
    model = "claude-sonnet-4-6"
    system = (
        "You are a senior researcher. Produce a brief, fact-grounded report. "
        "Cite evidence where possible."
    )

    def prompt(self, inputs: dict[str, Any], ctx: NodeContext) -> str:
        plan = inputs.get("state", {}).get("Planner", "")
        return f"Following this plan, write the final report:\n\n{plan}"


class EvidenceCritic(Verifier):
    """Fails any Worker output that doesn't mention 'evidence' or 'citation'."""

    def verify(self, ctx: NodeContext) -> VerifierResult:
        worker_output = str(ctx.state.get("Worker", "") or "")
        lower = worker_output.lower()
        if any(token in lower for token in ("evidence", "citation")):
            return VerifierResult(verdict="pass", score=1.0, reasons=["Citations present"])
        return VerifierResult(
            verdict="fail",
            score=0.2,
            reasons=[
                "Output does not meet the rigor bar.",
                "Try a different angle.",
            ],
        )


process = Process("research")
process.add_node("Planner", Planner(adapter), start=True)
process.add_node("Worker", Worker(adapter))
process.add_node("Critic", EvidenceCritic())

process.connect("Planner", "Worker")
process.connect("Worker", "Critic")
process.connect(
    "Critic", "Worker",
    condition="fail",
    policy=Policy(on_fail=Retry(max=3)),
)
process.connect("Critic", "end", condition="pass")


if __name__ == "__main__":
    # Headless: run, wait for the verifier to block the run, intervene
    # programmatically with an override prompt, and print the final state.
    import threading

    from overseer import Runtime
    from overseer.core.runtime import Intervention
    from overseer.persistence.store import Store

    runtime = Runtime(store=Store("overseer.db"))
    blocked = threading.Event()
    runtime.bus.on("run_blocked", lambda _e: blocked.set())

    holder: dict = {}

    def _go():
        holder["result"] = runtime.run(
            process, inputs={"task": "Survey renewable energy adoption."}
        )

    thread = threading.Thread(target=_go)
    thread.start()
    if blocked.wait(timeout=10):
        run_id = next(iter(runtime._control))
        runtime.submit(
            run_id,
            Intervention(
                action="retry",
                node="Worker",
                overrides={
                    "prompt": (
                        "Write the final report and include citations to at "
                        "least one credible source."
                    )
                },
            ),
        )
    thread.join(timeout=10)

    result = holder.get("result")
    print(f"\nrun {result.run_id} → {result.status.value}")
    for name, value in result.state.items():
        if name.startswith("__"):
            continue
        print(f"\n[{name}]\n{value}")
