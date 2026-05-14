# Examples

## `functional.py` — LangGraph-style decorators

Same Planner / Worker / Critic flow, written with `@process.node` and
`@process.verifier(after=..., retry=...)`. Demonstrates:

- Functions-as-nodes (no boilerplate classes).
- LangGraph-style state merging (return a dict, keys land on state).
- Auto-wired verifier edges (one decorator, three edges).
- `process.invoke(...)` for one-shot use.
- Any OpenAI-compatible LM via `OVERSEER_LM=ollama|groq|openai|anthropic`.

```bash
overseer run examples/functional.py                          # offline mock
OVERSEER_LM=ollama OVERSEER_MODEL=llama3.2 overseer run examples/functional.py
OVERSEER_LM=groq OVERSEER_MODEL=llama-3.3-70b-versatile overseer run examples/functional.py
```

## `research.py` — class-based agents

Same scenario expressed with explicit `Agent` and `Verifier` subclasses.
Shows the imperative API. Useful when you want fine-grained `prompt()` /
`parse()` hooks per agent or you're porting code from frameworks that
expect classes.

```bash
overseer run examples/research.py
```

## The four MVP acceptance steps (both examples)

1. **Run starts.** Planner builds a plan, Worker produces a draft.
2. **Verifier blocks.** Critic fails the Worker — no citations.
3. **Auto-retry exhausts.** `Retry(max=3)` re-runs Worker three times — same draft.
4. **You intervene.** Click the blocked node, type a prompt that mentions citations, press **Retry**. The next attempt passes; the run completes.

## Headless

```bash
python examples/functional.py   # programmatic intervention from inside the script
python examples/research.py     # same
```
