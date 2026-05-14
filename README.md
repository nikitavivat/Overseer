# Overseer

> An open-source framework for **reliable** multi-agent AI processes.
> Runtime, observability, and quality control in one place — not three.

Multi-agent systems don't crash. They **silently degrade**. A hallucination at
step 3 propagates downstream, accumulates context, and the final output looks
plausible but is wrong.

Overseer is built on a single hypothesis: quality control belongs **inside**
the runtime, not stapled on after the fact. Every step is a node in a graph.
Verifiers are first-class nodes. Every attempt is snapshotted. When the
system fails its own checks, it pauses and waits for you instead of pretending.

```python
from overseer import Process, VerifierResult
from overseer.adapters import openai_compatible

llm = openai_compatible(base_url="https://api.openai.com/v1", model="gpt-4o-mini")
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
        return VerifierResult(verdict="pass")
    return VerifierResult(verdict="fail", reasons=["No citations cited."])

process.connect("plan", "worker")

result = process.invoke({"task": "Survey renewables"})   # one-liner, LangGraph-style
```

Run the same graph live with a UI, snapshots, retry-from-any-node, and event payload inspection:

```bash
overseer run examples/functional.py
```

---

## Table of contents

- [Why Overseer](#why-overseer)
- [Installation](#installation)
- [60-second quickstart](#60-second-quickstart)
- [Core concepts](#core-concepts)
- [API reference](#api-reference)
  - [`Process`](#process)
  - [Decorators](#decorators)
  - [Nodes: `Agent`, `Function`, `Verifier`](#nodes)
  - [`VerifierResult`](#verifierresult)
  - [Policies: `Retry`, `Halt`](#policies)
  - [`Runtime` and `Intervention`](#runtime--intervention)
  - [Adapters](#adapters)
- [State model](#state-model)
- [Streaming and one-shot execution](#streaming-and-one-shot-execution)
- [CLI](#cli)
- [Visual UI](#visual-ui)
- [REST and WebSocket](#rest-and-websocket)
- [Persistence and time travel](#persistence-and-time-travel)
- [Examples](#examples)
- [Migrating from LangGraph](#migrating-from-langgraph)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Why Overseer

The market is split across four siloed categories. Each one solves a slice
of the problem and forces you to integrate the rest yourself.

| Category          | Examples                   | What they miss                              |
|-------------------|----------------------------|---------------------------------------------|
| Runtime           | LangGraph, CrewAI, AutoGen | No built-in quality layer, no UI            |
| Observability     | LangSmith, LangFuse        | After-the-fact only, no control loop        |
| Visual builders   | Flowise, Langflow          | Code/UI drift, no quality, no recovery      |
| Workflow engines  | Temporal, Inngest          | No LLM-specific primitives                  |

**Overseer's wedge:** the runtime, the observability layer, and the quality
gate are the same thing. Code is the source of truth — the UI mirrors
execution, never edits structure. Snapshots are open files (SQLite with JSON
payloads), so they're shareable, replayable, and grep-able.

---

## Installation

### Requirements

- Python 3.10+
- Optional: an OpenAI-compatible endpoint (OpenAI, Ollama, vLLM, Groq, OpenRouter, LM Studio, Anyscale, Fireworks, …) or Anthropic.

### From PyPI

```bash
pip install overseer-ai                    # core
pip install "overseer-ai[openai]"          # + OpenAI / any OpenAI-compatible endpoint
pip install "overseer-ai[anthropic]"       # + Anthropic Claude
pip install "overseer-ai[all]"             # everything
```

The PyPI distribution is `overseer-ai`; the Python import name is `overseer`:

```python
import overseer
from overseer import Process, VerifierResult
```

In your project's `pyproject.toml`:

```toml
[project]
dependencies = [
    "overseer-ai[openai]>=0.1.0",
]
```

### From git (unreleased changes)

```bash
pip install "overseer-ai[openai] @ git+https://github.com/nikitavivat/Overseer.git"
pip install "overseer-ai[openai] @ git+https://github.com/nikitavivat/Overseer.git@v0.1.0"
pip install "overseer-ai[openai] @ git+https://github.com/nikitavivat/Overseer.git@<sha>"
```

### For development

```bash
git clone https://github.com/nikitavivat/Overseer.git
cd Overseer
pip install -e ".[dev]"
pytest                                    # 33 tests
ruff check src tests examples
```

### Extras

| Extra              | Installs                                  | Required for                         |
|--------------------|-------------------------------------------|--------------------------------------|
| _(no extra)_       | `pydantic`, `click`, `fastapi`, `uvicorn` | Core graph, runtime, store, UI, CLI  |
| `[openai]`         | `openai>=1.30`                            | OpenAI proper + every OpenAI-compatible provider |
| `[anthropic]`      | `anthropic>=0.40`                         | Anthropic Claude                     |
| `[all]`            | both of the above                         | Everything                           |
| `[dev]`            | pytest, httpx, ruff, mypy                 | Contributing                         |

---

## 60-second quickstart

Create `agents.py`:

```python
import os
from overseer import Process, VerifierResult
from overseer.adapters import openai_compatible

llm = openai_compatible(
    base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    model="gpt-4o-mini",
)

process = Process("research")

@process.node(start=True)
def planner(state):
    plan = llm.complete(
        system="Output a 3-step plan.",
        user=f"Plan how to research: {state['task']}",
        model=llm.default_model,
    ).text
    return {"plan": plan}

@process.node
def writer(state, ctx):
    user = ctx.overrides.get("prompt") or (
        f"Write a report.\nPlan:\n{state['plan']}\nTopic: {state['task']}"
    )
    report = llm.complete(user=user, model=llm.default_model).text
    return {"report": report}

@process.verifier(after="writer", retry=2)
def critic(state) -> VerifierResult:
    if "[source:" in state.get("report", "").lower():
        return VerifierResult(verdict="pass")
    return VerifierResult(verdict="fail", reasons=["Add inline citations."])

process.connect("planner", "writer")

if __name__ == "__main__":
    print(process.invoke({"task": "Survey renewables"})["report"])
```

Run it three ways:

```bash
export OPENAI_API_KEY=sk-...
python agents.py                          # headless, prints the report
overseer run agents.py                    # launches the live UI on :8765
overseer serve agents.py --port 9000      # UI only, no auto-run
```

The decorator file must expose a module-level variable named `process` —
that's what the CLI loads.

---

## Core concepts

| Concept           | One-liner                                                                 |
|-------------------|---------------------------------------------------------------------------|
| **Process**       | The graph. Nodes + edges + policies. Source of truth.                     |
| **Node**          | A unit of work. Three kinds: `Agent`, `Function`, `Verifier`.             |
| **Edge**          | A directed connection between nodes, optionally routed by a condition.    |
| **Verifier**      | A node that returns `VerifierResult(verdict=pass\|fail\|retry\|escalate)`. Edges route on the verdict. |
| **Policy**        | Attached to an edge: `Retry(max=N)` or `Halt`. Retry budget is enforced.  |
| **Snapshot**      | Written before every node attempt. JSON in SQLite. Shareable, replayable. |
| **EventBus**      | Single shared bus. Runtime, persistence, and the UI are all subscribers.  |
| **Intervention**  | User-supplied control message: `retry`/`skip`/`abort`, with overrides.    |

When a verifier fails and the retry budget is exhausted, the run **blocks**
on the retry target node — not the verifier — because that's the node a
human would naturally fix. The UI drawer opens there. You can resume the
run with a new prompt or any other override.

---

## API reference

### `Process`

```python
from overseer import Process

process = Process("my-graph")
```

#### Imperative methods

```python
process.add_node(name: str, node_or_callable, *, start: bool = False) -> Process
process.connect(source: str, target: str, *, condition=None, policy=None) -> Process
process.start(name: str) -> Process            # mark a node as start
process.finish(name: str) -> Process           # shorthand for connect(name, "end")
```

- `add_node` accepts a `Node` instance, a callable (auto-wrapped as a
  `Function`), or any subclass of `Agent` / `Verifier`.
- `target="end"` is the reserved terminal sink.
- `condition` is one of: `None` (unconditional), a string (matched against
  `VerifierResult.verdict`), or a callable `(output) -> bool`.

#### `invoke(inputs)` and `stream(inputs)`

```python
state = process.invoke({"task": "..."})          # to completion → final state dict
for event in process.stream({"task": "..."}):    # event-by-event
    print(event.type, event.node_id, event.payload)
```

Both spin up an internal in-memory `Runtime`. If the process blocks (verifier
budget exhausted, node raised, edge routed nowhere), `invoke` raises
`overseer.core.graph.BlockedError` and `stream` ends. For interactive flows
that need human intervention, use a `Runtime` directly (see
[`Runtime`](#runtime--intervention)).

#### Validation and topology

```python
report = process.validate()        # errors + warnings (unreachable, dead-end, cycles)
process.topology()                 # serializable dict, used by the UI
```

### Decorators

```python
@process.node                                   # auto name from fn.__name__
def planner(state): ...

@process.node(name="Planner", start=True)
def planner(state): ...

@process.verifier(after="worker", retry=3, on_pass="end")
def critic(state) -> VerifierResult: ...
```

`@process.verifier(after=X, retry=N)` declares three edges in one place:

- `X → critic` (unconditional)
- `critic → X` on `fail`, with `Policy(on_fail=Retry(max=N))` if `N > 0`
- `critic → end` on `pass` (override with `on_pass="<other_node>"`)

Decorated function signatures supported by `@process.node`:

| Signature             | Receives                                            |
|-----------------------|-----------------------------------------------------|
| `def f(state)`        | The merged state dict                               |
| `def f(state, ctx)`   | State + `NodeContext` (attempt, overrides, last verifier) |
| `def f(inputs, ctx)`  | Classic Overseer form                               |
| `def f()`             | No args                                             |

Return forms:

- `dict` → keys (excluding `__` prefix) are merged into top-level state.
- Anything else → stored under `state[node_name]`.

### Nodes

#### `Agent`

LLM-backed node. Subclass for fine-grained control over prompt and parsing.

```python
from overseer import Agent
from overseer.adapters import openai_compatible

llm = openai_compatible(base_url="...", model="gpt-4o-mini")

class Planner(Agent):
    model = "gpt-4o-mini"
    system = "You are a planner."
    temperature = 0.2

    def prompt(self, inputs, ctx):
        return f"Plan: {inputs['inputs']['task']}"

    def parse(self, text, ctx):
        return [line for line in text.splitlines() if line.strip()]

process.add_node("planner", Planner(llm), start=True)
```

When a verifier fails and retries, Overseer auto-folds the verifier's
`reasons` into the next prompt via `ctx.overrides["critic_feedback"]`.
You don't need to plumb it manually.

#### `Function`

Deterministic node. Created implicitly by `@process.node` and `add_node(name, callable)`. Use directly when you want explicit construction:

```python
from overseer import Function

def split(state):
    return {"chunks": state["doc"].split("\n\n")}

process.add_node("split", Function(split))
```

#### `Verifier`

Quality gate. Either subclass, or use `@process.verifier`.

```python
from overseer import Verifier, VerifierResult

class HasCitations(Verifier):
    def verify(self, ctx):
        if "[source:" in ctx.state.get("report", "").lower():
            return VerifierResult(verdict="pass", score=1.0)
        return VerifierResult(verdict="fail", reasons=["Missing citations."])
```

### `VerifierResult`

```python
from overseer import VerifierResult

VerifierResult(
    verdict="pass",           # "pass" | "fail" | "retry" | "escalate"
    score=0.92,               # optional float
    reasons=["..."],          # explanations; surfaced in retries and UI
    suggested_fix={"...": ""} # optional dict for tool-augmented critics
)
```

Edges route on `verdict`:

```python
process.connect("critic", "worker", condition="fail", policy=Policy(on_fail=Retry(max=3)))
process.connect("critic", "end", condition="pass")
process.connect("critic", "human_review", condition="escalate")
```

### Policies

```python
from overseer import Policy, Retry, Halt

# Retry the inbound edge up to N times. When exhausted, the run blocks
# on the retry target and waits for a user intervention.
Policy(on_fail=Retry(max=3, with_critic="critic"))

# Stop the run on fail. Useful for hard gates.
Policy(on_fail=Halt(notify=["oncall"]))
```

The `with_critic` field is informational and surfaced to UIs; the runtime
uses it for retry-context labeling.

### `Runtime` and `Intervention`

Use `Runtime` directly when you need to submit human interventions
programmatically (tests, custom UIs, automation).

```python
import threading
from overseer import Runtime
from overseer.core.runtime import Intervention
from overseer.persistence.store import Store

runtime = Runtime(store=Store("overseer.db"))

def _run():
    return runtime.run(process, inputs={"task": "Survey X"})

threading.Thread(target=_run).start()

# When you see a `run_blocked` event, send an intervention:
runtime.bus.on("run_blocked", lambda e: runtime.submit(
    e.run_id,
    Intervention(
        action="retry",            # "retry" | "skip" | "abort"
        node="worker",             # node to retry (defaults to the blocked one)
        overrides={"prompt": "Write the report and cite sources."},
    ),
))
```

`Runtime.run` is synchronous; the thread blocks until the run completes,
aborts, or fails. The `bus` is shared and pluggable.

### Adapters

All adapters implement `LLMAdapter.complete(*, system, user, model, ...)` and
return a `Completion` object with `.text` and `.usage`.

```python
from overseer.adapters import (
    MockAdapter,                        # offline, deterministic
    openai_compatible,                  # any OpenAI-compatible endpoint
    ollama, groq,                       # convenience presets
)
from overseer.adapters import OpenAIAdapter, AnthropicAdapter   # optional extras

# Pick one:
llm = MockAdapter(lambda *, system, user, model: "fixture")
llm = OpenAIAdapter(default_model="gpt-4o-mini")
llm = AnthropicAdapter(default_model="claude-opus-4-7")
llm = ollama("llama3.2")                            # localhost:11434/v1
llm = ollama("qwen2.5:7b", host="http://gpu:11434")
llm = groq("llama-3.3-70b-versatile")               # reads GROQ_API_KEY
llm = openai_compatible(
    base_url="https://openrouter.ai/api/v1",
    model="anthropic/claude-opus-4-7",
    api_key="sk-or-...",
    timeout=60,
    extra_headers={"HTTP-Referer": "https://example.com"},
)
```

Reads `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GROQ_API_KEY` from the
environment if `api_key` is omitted.

---

## State model

Hybrid: LangGraph-style top-level keys **plus** per-node positional storage.

```python
process.invoke({"task": "X"})

# After planner returns {"plan": "P"} and worker returns {"report": "R"}:
state == {
    "task": "X",                  # initial inputs spread at top level
    "__inputs__": {"task": "X"},  # full inputs preserved verbatim
    "plan": "P",                  # merged from planner's dict return
    "report": "R",                # merged from worker's dict return
    "planner": {"plan": "P"},     # also stored under node name
    "worker":  {"report": "R"},   # ditto — handy for diffing attempts
    "critic":  {"verdict": "pass", "score": 1.0, "reasons": [], ...},
}
```

Rules:

- Initial inputs are spread at the top level so nodes can read `state["task"]` directly.
- `Function` nodes returning a `dict` have their keys merged into the top level (`__`-prefixed keys are skipped).
- Every node's output is also stored under `state[node_name]`, including verifiers.
- `Agent` outputs are kept under the node name only — they are positional, not state updates. Use a `Function` wrapper if you want an Agent's output merged.

---

## Streaming and one-shot execution

```python
# Blocking — returns final state, raises BlockedError if the run blocks.
state = process.invoke({"task": "..."})

# Iterator of events — generator ends when the run terminates.
for event in process.stream({"task": "..."}):
    print(f"{event.type:18}  {event.node_id or '-':10}  {event.payload}")
```

Event types you'll see:

`run_started`, `node_started`, `node_completed`, `node_failed`,
`node_blocked`, `verifier_pass`, `verifier_fail`, `verifier_retry`,
`run_blocked`, `run_resumed`, `user_intervention`, `run_completed`, `run_failed`.

Each `Event` has `run_id`, `node_id`, `type`, `payload`, `timestamp`, `event_id`.

---

## CLI

```
overseer --help
```

| Command           | What it does                                                  |
|-------------------|---------------------------------------------------------------|
| `overseer run`    | Load a process file, start the server, optionally fire a run. |
| `overseer serve`  | Serve the UI without auto-starting a run.                     |
| `overseer replay` | Print a stored snapshot from a SQLite store.                  |

```bash
overseer run path/to/agents.py
overseer run path/to/agents.py --host 0.0.0.0 --port 9000 --no-open --no-auto-start --task "..."
overseer serve path/to/agents.py --db ./runs.db
overseer replay <snapshot_id> --db ./runs.db
```

The file passed to `run` / `serve` is imported as a Python module and must
expose a top-level variable named `process` (a `Process` instance).

---

## Visual UI

`overseer run <file.py>` launches a vanilla-JS UI at `http://localhost:8765`.

- **Graph** — laid out by Dagre, coloured by status (pending, running, ok, fail, blocked).
- **Node labels** — show attempt counter (`×3`) and last duration (`240ms`/`1.24s`).
- **Drawer** — click any node → status pill, latest output, last failure (if any), verifier verdict, full snapshot history (expandable), intervention panel.
- **Events** — right panel; click any row to expand the full JSON payload.
- **Runs sidebar** — every run with status and total duration; click to inspect.
- **Live updates** — WebSocket; auto-reconnects on drop.
- **Topbar** — task input + Start button; status pill reflects the active run.

Resume a blocked run from the UI: click the yellow node → in the drawer's
"Retry with override" section, type a new prompt → press **Retry**. The
runtime resumes with `ctx.overrides["prompt"]` set for the next attempt.

---

## REST and WebSocket

The control plane is plain JSON over FastAPI. Everything the UI does is
just HTTP — automate it.

| Method | Path                                  | Body                                       | Response |
|--------|---------------------------------------|--------------------------------------------|----------|
| GET    | `/api/health`                         | —                                          | `{"status":"ok","process":"<name>"}` |
| GET    | `/api/graph`                          | —                                          | `process.topology()` |
| GET    | `/api/runs`                           | —                                          | list of runs |
| GET    | `/api/runs/{run_id}`                  | —                                          | `{status, blocked_node, state, ...}` |
| GET    | `/api/runs/{run_id}/events?after=<ts>`| —                                          | list of events |
| GET    | `/api/runs/{run_id}/snapshots`        | —                                          | list of snapshots |
| POST   | `/api/runs`                           | `{"inputs": {...}}`                        | `{"run_id":"..."}` |
| POST   | `/api/runs/{run_id}/intervene`        | `{"action":"retry","node":"worker","overrides":{...}}` | `{"status":"submitted"}` |
| WS     | `/api/stream`                         | —                                          | live event stream |

End-to-end with `curl`:

```bash
RUN=$(curl -s -X POST :8765/api/runs -H 'content-type: application/json' \
  -d '{"inputs":{"task":"X"}}' | jq -r .run_id)

# wait for block
while [ "$(curl -s :8765/api/runs/$RUN | jq -r .status)" != "blocked" ]; do sleep 0.5; done

# resume with an override prompt
curl -X POST :8765/api/runs/$RUN/intervene -H 'content-type: application/json' \
  -d '{"action":"retry","node":"worker","overrides":{"prompt":"...cite sources..."}}'

# final state
curl -s :8765/api/runs/$RUN | jq .state
```

---

## Persistence and time travel

Everything is stored in SQLite (WAL mode by default).

```
runs        (run_id, process_name, status, started_at, ended_at)
events      (event_id, run_id, node_id, type, payload JSON, ts)
snapshots   (snapshot_id, run_id, node_id, data JSON, ts)
```

A snapshot is written **before every node attempt**, capturing the full
state, the resolved overrides, and the attempt number.

```python
from overseer.persistence.store import Store

store = Store("overseer.db")
store.list_runs(limit=50)
store.list_events(run_id, after=None)
store.list_snapshots(run_id)
store.latest_snapshot(run_id, node_id="worker")
store.get_snapshot(snapshot_id)
```

Inspect a single snapshot from the CLI:

```bash
overseer replay <snapshot_id>
```

Full snapshot **replay** (re-running from a checkpoint) and **branch forks**
land in v0.2 — see the [Roadmap](#roadmap).

---

## Examples

The repo includes two complete examples:

| File                       | Style                       | Demonstrates |
|----------------------------|-----------------------------|--------------|
| `examples/functional.py`   | Decorators + state-merge    | LangGraph-parity DX, `@process.node`, `@process.verifier`, `OVERSEER_LM` env-switch |
| `examples/research.py`     | Class-based Agents          | Subclassing `Agent` and `Verifier` with `prompt` / `parse` / `verify` hooks |

Run any of them:

```bash
overseer run examples/functional.py
python examples/functional.py        # headless, with programmatic intervention
OVERSEER_LM=ollama OVERSEER_MODEL=llama3.2 overseer run examples/functional.py
```

See [`examples/README.md`](examples/README.md) for the four-step acceptance
walk-through (planner runs → critic fails → retries exhaust → user intervenes).

---

## Migrating from LangGraph

Most idioms map 1:1.

| LangGraph                                   | Overseer                                                   |
|---------------------------------------------|------------------------------------------------------------|
| `graph.add_node("plan", plan_fn)`           | `@process.node(name="plan")` or `process.add_node(...)`    |
| `graph.set_entry_point("plan")`             | `start=True` on the first `@process.node`, or `.start()`   |
| `graph.add_edge("plan", "worker")`          | `process.connect("plan", "worker")`                        |
| `graph.add_conditional_edges(...)`          | `condition="pass" \| "fail" \| callable` on `connect`      |
| `graph.compile().invoke({...})`             | `process.invoke({...})`                                    |
| `graph.compile().stream({...})`             | `process.stream({...})`                                    |
| `TypedDict` state + reducer                 | Partial dicts merged into top-level state                  |
| _(missing)_ quality gating                  | `@process.verifier(after="worker", retry=3)`               |
| _(missing)_ time-travel and human-in-loop   | Snapshots + REST `intervene` built-in                      |
| _(missing)_ visual viewer                   | `overseer run …` ships a live UI                           |

---

## Troubleshooting

**`ImportError: OpenAIAdapter requires the openai package`** — install with
the extra: `pip install "overseer[openai]"` or `pip install openai`.

**`KeyError: 'OPENAI_API_KEY'`** — the adapter reads it from the environment
automatically; you don't need `os.environ["OPENAI_API_KEY"]` in your script.
Set `export OPENAI_API_KEY=...` or pass `api_key=...` directly.

**`BlockedError: Process blocked on node 'worker'`** — `process.invoke()`
hit the verifier retry budget. Either run via `Runtime` and submit an
`Intervention`, or use `overseer run` and resume from the UI. To make it
auto-fix more often, increase the `retry=N` on `@process.verifier`.

**`Did not find branch or tag 'v0.1.0'`** during `pip install` from git —
the tag doesn't exist yet in your fork. Either install from a branch (`@main`)
or create the tag (`git tag v0.1.0 && git push --tags`).

**`No matching distribution found for overseer-ai`** — the latest version
hasn't propagated to your local pip cache yet. Try `pip install -U pip` then
`pip install --no-cache-dir overseer-ai`.

**Process file not loading** — the CLI looks for a module-level variable
named `process`. Make sure your file does `process = Process(...)` at the
top level, not inside `if __name__ == "__main__":`.

**Port already in use** — `overseer run --port 9000` to pick a free port,
or `lsof -i :8765 -t | xargs kill` to free the default.

**`overseer.db-wal` keeps growing** — that's SQLite's WAL. It's checkpointed
automatically on close. Safe to delete when no run is active. Already in
`.gitignore`.

---

## Roadmap

`v0.1` (current) — **MVP**

- Declarative graph: nodes, edges, policies
- Decorator API (`@process.node`, `@process.verifier`)
- Imperative API (`Agent`, `Verifier`, `Function` subclasses)
- `invoke()` and `stream()` (LangGraph parity)
- Retry budget + user intervention via REST/UI
- Auto-fold critic feedback into Agent retries
- SQLite persistence (events + snapshots)
- Adapters: Anthropic, OpenAI, any OpenAI-compatible (Ollama / vLLM / Groq / OpenRouter / LM Studio / …), Mock
- Live UI: graph, attempt badges, durations, snapshot history, event payload inspection
- CLI: `run`, `serve`, `replay`

`v0.2` — **time travel**

- Full snapshot replay (re-run a node from a checkpoint)
- Branch forks and diff
- Postgres backend
- Cost and time budgets (tokens, dollars, wall-clock)

`v0.3+`

- Drag-and-drop subgraphs in the UI (still code-as-truth)
- Parallel edges and fan-in
- Tool-use integration for Verifiers (a critic that can grep code, query a DB, etc.)
- Distributed runtime
- Plugin system for custom node kinds

See [`NOTES.md`](NOTES.md) for the full technical spec.

---

## Contributing

```bash
git clone https://github.com/nikitavivat/Overseer.git
cd Overseer
pip install -e ".[dev]"

pytest                                    # 33 tests, ~5s
ruff check src tests examples             # lint
ruff format src tests examples            # format

python -m build --wheel                   # build a wheel
```

Project layout:

```
src/overseer/
├── __init__.py            # public exports
├── cli.py                 # `overseer` entry point
├── core/
│   ├── contracts.py       # Pydantic models: VerifierResult, NodeContext
│   ├── events.py          # Event + EventBus
│   ├── graph.py           # Process, Edge, decorators, invoke/stream
│   └── runtime.py         # Synchronous executor + intervention loop
├── nodes/
│   ├── agent.py           # Agent (LLM-backed)
│   ├── function.py        # Function (deterministic)
│   ├── verifier.py        # Verifier + @verifier wrapper
│   └── base.py            # Node ABC
├── quality/policies.py    # Retry, Halt, Policy
├── persistence/store.py   # SQLite store (runs, events, snapshots)
├── adapters/              # Mock, OpenAI, Anthropic, presets
├── control/api.py         # FastAPI + WebSocket control plane
└── ui/static/             # vanilla JS + Cytoscape.js UI
```

Open an issue before a non-trivial PR — we'd rather agree on the shape than
review-and-reject. Small fixes, docs, and additional adapters are always
welcome.

---

## License

Apache 2.0. The core stays free forever. See [`LICENSE`](LICENSE).
