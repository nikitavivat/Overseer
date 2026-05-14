"""LangGraph-style example: decorators + dict state-merge + OpenAI-compatible.

Three nodes wired entirely through decorators. The verifier auto-wires its
own edges (worker → critic → worker on fail / → end on pass) — declared in
one place.

LM backend selection (in priority order):
  * OVERSEER_LM=ollama      → ollama("llama3.2") at localhost:11434
  * OVERSEER_LM=groq        → groq(model) using GROQ_API_KEY
  * OVERSEER_LM=openai      → OpenAI proper (OPENAI_API_KEY)
  * OVERSEER_LM=anthropic   → Anthropic (ANTHROPIC_API_KEY)
  * default                 → MockAdapter (offline, deterministic)

Run:

  overseer run examples/functional.py

For Ollama:

  ollama run llama3.2
  OVERSEER_LM=ollama overseer run examples/functional.py
"""

from __future__ import annotations

import os

from overseer import Process, VerifierResult
from overseer.adapters import MockAdapter
from overseer.adapters.base import LLMAdapter

UNLOCK_PHRASE = "include citations"


def _mock(*, system: str, user: str, model: str) -> str:
    if "plan how to" in user.lower():
        return "1. find sources  2. summarize  3. cross-check"
    if UNLOCK_PHRASE in user.lower():
        return (
            "Final report — adoption of renewables has accelerated. "
            "Citations: [IEA 2024], [IRENA 2023]. Evidence is consistent."
        )
    return "Generic draft. No supporting references."


def _build_adapter() -> LLMAdapter:
    backend = os.getenv("OVERSEER_LM", "").lower()
    if backend == "ollama":
        from overseer.adapters import ollama

        return ollama(os.getenv("OVERSEER_MODEL", "llama3.2"))
    if backend == "groq":
        from overseer.adapters import groq

        return groq(os.getenv("OVERSEER_MODEL", "llama-3.3-70b-versatile"))
    if backend == "openai":
        from overseer.adapters import OpenAIAdapter

        return OpenAIAdapter(default_model=os.getenv("OVERSEER_MODEL", "gpt-4o-mini"))
    if backend == "anthropic" or (os.getenv("ANTHROPIC_API_KEY") and not backend):
        from overseer.adapters import AnthropicAdapter

        return AnthropicAdapter(default_model=os.getenv("OVERSEER_MODEL", "claude-opus-4-7"))
    return MockAdapter(_mock)


llm = _build_adapter()


def _chat(system: str, user: str) -> str:
    completion = llm.complete(system=system, user=user, model=getattr(llm, "default_model", "mock"))
    return completion.text


process = Process("research-functional")


@process.node(start=True)
def planner(state):
    """Plain function as a node. Receives full state, returns dict that
    merges into state at the top level (LangGraph-style)."""
    plan = _chat(
        system="You are a planner. Output a 3-step plan.",
        user=f"Plan how to: {state['task']}",
    )
    return {"plan": plan}


@process.node
def worker(state, ctx):
    """Functional nodes can opt into overrides by accepting `ctx` — the user
    edits the prompt from the UI and we honour it here."""
    user = ctx.overrides.get("prompt") or (
        f"Following this plan, write the report:\n{state['plan']}"
    )
    report = _chat(system="You are a senior researcher.", user=user)
    return {"report": report}


@process.verifier(after="worker", retry=3)
def critic(state) -> VerifierResult:
    """Auto-wires three edges:
      worker → critic
      critic → worker (on fail, Retry(max=3))
      critic → end (on pass)
    """
    report = state.get("report", "")
    if any(token in report.lower() for token in ("citation", "evidence")):
        return VerifierResult(verdict="pass", score=1.0)
    return VerifierResult(
        verdict="fail",
        score=0.2,
        reasons=[
            "Report lacks rigor.",
            "Tighten it up.",
        ],
    )


process.connect("planner", "worker")


if __name__ == "__main__":
    # Headless: stream events to stdout, intervene if the run blocks.
    import threading

    from overseer import Runtime
    from overseer.core.runtime import Intervention
    from overseer.persistence.store import Store

    runtime = Runtime(store=Store("overseer.db"))
    blocked = threading.Event()

    runtime.bus.on_any(
        lambda e: print(
            f"[{e.timestamp:.3f}] {e.type:20} {e.node_id or '-':10} "
            f"{ {k: v for k, v in e.payload.items() if k != 'state'} }"
        )
    )
    runtime.bus.on("run_blocked", lambda _e: blocked.set())

    holder: dict = {}

    def _run():
        holder["r"] = runtime.run(process, inputs={"task": "Survey renewables."})

    t = threading.Thread(target=_run)
    t.start()
    if blocked.wait(timeout=20):
        run_id = next(iter(runtime._control))
        runtime.submit(
            run_id,
            Intervention(
                action="retry",
                node="worker",
                overrides={
                    "prompt": "Write a final report and include citations to credible sources."
                },
            ),
        )
    t.join(timeout=30)

    r = holder.get("r")
    if r:
        print(f"\nFINAL → {r.status.value}")
        print(f"state.report = {r.state.get('report', '')[:160]}")
