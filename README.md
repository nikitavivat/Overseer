# Overseer

> Open-source framework for **reliable** multi-agent AI processes. Runtime, observability and quality control in one place — not three.

Multi-agent systems don't crash. They **silently degrade**. A hallucination at step 3 propagates downstream, accumulates context, and the final output looks plausible but is wrong.

Overseer fixes that. Quality checks are first-class nodes in the graph. Every step is snapshotted and replayable. When something fails, you intervene from the UI without restarting the whole flow.

```python
from overseer import Process, VerifierResult
from overseer.adapters import ollama  # or groq / openai_compatible / AnthropicAdapter

llm = ollama("llama3.2")              # OpenAI-compatible — works against any endpoint
process = Process("research")

@process.node(start=True)
def plan(state):
    return {"plan": llm.complete(user=f"Plan: {state['task']}", model=llm.default_model).text}

@process.node
def worker(state, ctx):
    user = ctx.overrides.get("prompt") or f"Write a report for: {state['plan']}"
    return {"report": llm.complete(user=user, model=llm.default_model).text}

@process.verifier(after="worker", retry=3)
def critic(state) -> VerifierResult:
    if "citation" in state.get("report", "").lower():
        return VerifierResult(verdict="pass", score=1.0)
    return VerifierResult(verdict="fail", reasons=["No citations cited."])

process.connect("plan", "worker")

result = process.invoke({"task": "Survey renewables"})  # one-liner like LangGraph
```

The same graph runs live in the UI — with retry-from-any-node, snapshots, durations, and event payload inspection:

```bash
overseer run examples/functional.py
```

## Why Overseer

The market is split across four siloed categories:

| Category              | Examples                   | Gap                                       |
|-----------------------|----------------------------|-------------------------------------------|
| Runtime               | LangGraph, CrewAI, AutoGen | No built-in quality layer, no UI          |
| Observability         | LangSmith, LangFuse        | After-the-fact only, no control loop      |
| Visual builders       | Flowise, Langflow          | Code/UI drift, no quality, no recovery    |
| Workflow engines      | Temporal, Inngest          | No LLM-specific primitives                |

**Overseer's wedge:** runtime, observability and quality control are one thing — not three. Code is the source of truth. The UI reflects execution, never edits structure. Snapshots are open files (SQLite/JSON).

## Install

```bash
pip install overseer                    # core
pip install overseer[openai]            # OpenAI + any OpenAI-compatible (Ollama, vLLM, Groq, Together, LM Studio, OpenRouter, ...)
pip install overseer[anthropic]         # Anthropic
pip install overseer[all]               # everything
```

## Quickstart (offline)

```bash
pip install -e ".[dev]"
overseer run examples/functional.py
```

Opens `http://localhost:8765` automatically and starts a run against a deterministic offline mock — the Critic fails the Worker; click the blocked node, type a prompt that mentions "citations", hit **Retry**, watch it pass.

## API surface

### Declarative — LangGraph-style decorators

```python
from overseer import Process, VerifierResult

process = Process("graph")

@process.node(start=True)
def planner(state):                  # plain function — auto-wrapped as a node
    return {"plan": ...}             # dict returns are merged into state

@process.node
def worker(state, ctx):              # opt into `ctx` to read overrides on retry
    return {"report": ...}

@process.verifier(after="worker", retry=3)
def critic(state) -> VerifierResult: # auto-wires: worker→critic, critic→worker (fail), critic→end (pass)
    ...

process.connect("planner", "worker")
state = process.invoke({"task": "..."})        # to completion
for ev in process.stream({"task": "..."}):     # event-by-event
    ...
```

### Imperative — class-based agents

```python
from overseer import Process, Agent, Verifier, VerifierResult, Policy, Retry

class Planner(Agent):
    model = "claude-opus-4-7"
    def prompt(self, inputs, ctx): return f"Plan: {inputs['inputs']['task']}"

class Worker(Agent):
    model = "claude-sonnet-4-6"
    def prompt(self, inputs, ctx): return f"Write report for: {inputs['state']['Planner']}"

class Check(Verifier):
    def verify(self, ctx):
        return VerifierResult(verdict="pass" if "evidence" in ctx.state["Worker"] else "fail")

process = (
    Process("research")
    .add_node("Planner", Planner(adapter), start=True)
    .add_node("Worker", Worker(adapter))
    .add_node("Check", Check())
    .connect("Planner", "Worker")
    .connect("Worker", "Check")
    .connect("Check", "Worker", condition="fail", policy=Policy(on_fail=Retry(max=3)))
    .connect("Check", "end", condition="pass")
)
```

Both styles compose: drop in an `Agent` next to a `@process.node` function.

## OpenAI-compatible providers

`overseer[openai]` ships an adapter that talks to anything speaking OpenAI's Chat Completions API. Use a preset or the generic factory:

```python
from overseer.adapters import ollama, groq, openai_compatible, OpenAIAdapter

llm = ollama("llama3.2")                                # localhost:11434/v1
llm = ollama("qwen2.5:7b", host="http://gpu-box:11434") # custom host
llm = groq("llama-3.3-70b-versatile")                   # reads GROQ_API_KEY
llm = openai_compatible(                                # everything else
    base_url="https://openrouter.ai/api/v1",
    model="anthropic/claude-opus-4-7",
    api_key="...",
)
llm = OpenAIAdapter(default_model="gpt-4o-mini")        # official OpenAI
```

The same `Agent` and `process.node` code runs unchanged across providers — swap the adapter, that's it.

## State model

Initial inputs are spread at the top level (LangGraph-style) and also kept under `__inputs__` for explicit access. Functional nodes that return a `dict` have their keys merged into state. Anything else is stored under `state[node_name]`.

```python
process.invoke({"task": "X"})
# After plan returns {"plan": "P"} and worker returns {"report": "R"}:
state == {
    "task": "X",
    "__inputs__": {"task": "X"},
    "plan": "P",        "planner": {"plan": "P"},
    "report": "R",      "worker": {"report": "R"},
}
```

## Visual viewer

`overseer run <file.py>` launches the live UI:

- Graph laid out by Dagre, colored by status (pending / running / ok / fail / blocked).
- Node label shows attempt count (`×3`) and duration (`240ms`).
- Click any node → drawer with status, output, snapshot history, verifier verdict, intervention panel.
- Click any event in the right panel → expand to see the full payload.
- WebSocket live updates. Multiple runs in parallel; click in the run list to inspect history.

Headless mode (no UI): use `process.invoke()` / `process.stream()`, or run the CLI with `--no-ui` style flags (`overseer serve` skips auto-run; `overseer replay <snapshot_id>` prints a snapshot).

## Core concepts

- **Process** — the graph: nodes + edges + policies. Source of truth.
- **Node** — a unit of work. `Agent` for LLM calls, `Function` for deterministic code, `Verifier` for quality gates.
- **Verifier** — a node that returns `VerifierResult(verdict=pass|fail|retry|escalate, …)`. Edges are routed by verdict.
- **Policy** — applied to an edge: `Retry`, `Halt`. Retry budget is enforced; on exhaustion the run blocks and waits for intervention.
- **Snapshot** — written before every node. Open format (JSON in SQLite). Shareable, replayable.
- **EventBus** — single shared bus. Runtime, persistence, and the UI are all subscribers.

## Migrating from LangGraph

Most idioms map 1:1:

| LangGraph                                  | Overseer                                                  |
|--------------------------------------------|-----------------------------------------------------------|
| `graph.add_node("plan", plan_fn)`          | `@process.node(name="plan")` or `process.add_node(...)`   |
| `graph.set_entry_point("plan")`            | `start=True` on the first `@process.node`, or `.start()`  |
| `graph.add_edge("plan", "worker")`         | `process.connect("plan", "worker")`                       |
| `graph.add_conditional_edges(...)`         | edges with `condition="pass"`/`"fail"`/callable           |
| `graph.compile().invoke({...})`            | `process.invoke({...})`                                   |
| `graph.compile().stream({...})`            | `process.stream({...})`                                   |
| state TypedDict + reducer                  | partial dicts merged into state (top-level keys)          |
| _(missing)_ quality gating                 | `@process.verifier(after="worker", retry=3)`              |
| _(missing)_ time-travel & intervention     | snapshots + control plane built-in                        |

## Status

`v0.1` — MVP. See `NOTES.md` for the full technical spec and roadmap.

Working today:
- Decorator + class APIs, `invoke()` and `stream()`
- Graph, runtime, retry policies, user intervention
- Verifiers (custom + decorator auto-wired)
- SQLite persistence (journal + snapshots)
- Anthropic, OpenAI, OpenAI-compatible (Ollama / Groq / OpenRouter / vLLM / LM Studio) + Mock adapters
- Live UI: per-node duration & attempt badges, snapshot history in drawer, event payload inspector
- CLI: `run`, `serve`, `replay`

Coming next (v0.2+):
- Full snapshot replay (CLI subcommand inspects today)
- Branch forking + diff
- Budgets (tokens, dollars, time)
- Postgres backend

## License

Apache 2.0. The core stays free forever.
