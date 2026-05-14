"""Process: graph declaration with nodes, edges, and policies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from overseer.quality.policies import Policy

if TYPE_CHECKING:
    from overseer.nodes.base import Node

TERMINAL = "end"


class BlockedError(RuntimeError):
    """Raised by `Process.invoke` when a run blocks (needs human intervention)."""


EdgeCondition = str | Callable[[Any], bool] | None


@dataclass
class Edge:
    """Directed edge with an optional routing condition and policy.

    Condition forms:
      * `None` — unconditional.
      * string literal (`"pass"`, `"fail"`, ...) — matches a `VerifierResult.verdict`.
      * callable `(output) -> bool` — arbitrary predicate.
    """

    source: str
    target: str
    condition: EdgeCondition = None
    policy: Policy | None = None

    def label(self) -> str:
        if self.condition is None:
            return ""
        if isinstance(self.condition, str):
            return self.condition
        return "fn"


@dataclass
class GraphValidation:
    """Outcome of a graph validation pass."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class Process:
    """Declarative graph: nodes + edges + policies.

    Source of truth for execution. The runtime walks it, the UI mirrors it.
    Mutations to the graph after `run()` starts are not supported and not
    reflected in already-started runs.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.start_node: str | None = None

    def add_node(
        self,
        name: str,
        node: Node | Callable[..., Any],
        *,
        start: bool = False,
    ) -> Process:
        """Register a node. Plain callables are auto-wrapped as `Function`."""
        from overseer.nodes.base import Node as _Node
        from overseer.nodes.function import Function

        if callable(node) and not isinstance(node, _Node):
            node = Function(node, name=name)
        if not isinstance(node, _Node):
            raise TypeError(f"Expected Node or callable for {name!r}, got {type(node).__name__}")
        if name == TERMINAL:
            raise ValueError(f"Node name {TERMINAL!r} is reserved as the terminal sink")
        if name in self.nodes:
            raise ValueError(f"Node {name!r} already defined")
        node.name = name
        self.nodes[name] = node
        if start or self.start_node is None:
            self.start_node = name
        return self

    def connect(
        self,
        source: str,
        target: str,
        *,
        condition: EdgeCondition = None,
        policy: Policy | None = None,
    ) -> Process:
        if source not in self.nodes:
            raise ValueError(f"Unknown source node {source!r}")
        if target != TERMINAL and target not in self.nodes:
            raise ValueError(f"Unknown target node {target!r}")
        self.edges.append(Edge(source=source, target=target, condition=condition, policy=policy))
        return self

    def start(self, name: str) -> Process:
        """Mark a node as the start node (idempotent)."""
        if name not in self.nodes:
            raise ValueError(f"Unknown node {name!r}; add it before calling start()")
        self.start_node = name
        return self

    def finish(self, name: str) -> Process:
        """Shorthand for `connect(name, "end")`."""
        return self.connect(name, TERMINAL)

    # ---------- decorator API ----------

    def node(
        self,
        _fn: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        start: bool = False,
    ) -> Any:
        """Register a function as a node.

        Supports both forms:

            @process.node
            def plan(state): ...

            @process.node(name="Planner", start=True)
            def plan(state): ...
        """

        def _register(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.add_node(name or fn.__name__, fn, start=start)
            return fn

        if callable(_fn):
            return _register(_fn)
        return _register

    def verifier(
        self,
        _fn: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        after: str | None = None,
        retry: int = 0,
        on_pass: str = TERMINAL,
    ) -> Any:
        """Register a verifier function and (optionally) auto-wire its edges.

        Usage:

            @process.verifier(after="Worker", retry=3)
            def critic(state) -> VerifierResult: ...

        With `after="Worker"`:
          * connects `Worker → critic`
          * connects `critic → Worker` on `fail` (with Retry(max=retry) if >0)
          * connects `critic → end` on `pass`

        Without `after`, you connect edges manually.
        """
        from overseer.nodes.verifier import _function_verifier
        from overseer.quality.policies import Retry as _Retry

        def _register(fn: Callable[..., Any]) -> Callable[..., Any]:
            verifier_name = name or fn.__name__
            wrapper = _function_verifier(fn, verifier_name)
            self.add_node(verifier_name, wrapper)
            if after is not None:
                if after not in self.nodes:
                    raise ValueError(f"verifier(after={after!r}): unknown node")
                self.connect(after, verifier_name)
                policy = Policy(on_fail=_Retry(max=retry)) if retry > 0 else None
                self.connect(
                    verifier_name, after, condition="fail", policy=policy,
                )
                self.connect(verifier_name, on_pass, condition="pass")
            return fn

        # Reject bare `@process.verifier` without `after` if `_fn` is a
        # callable — `after` is the high-value path, force a parenthesized form
        # to keep the decision visible at the call site.
        if callable(_fn):
            return _register(_fn)
        return _register

    # ---------- invoke / stream ----------

    def invoke(
        self,
        inputs: dict[str, Any] | None = None,
        *,
        store: Any | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Run to completion and return the final state.

        If the process blocks (verifier retry budget exhausted, a node raises),
        invoke aborts the run and raises `BlockedError`. For interactive flows
        use `Runtime` directly so you can submit interventions.
        """
        from overseer.core.runtime import Intervention, Runtime
        from overseer.persistence.store import Store

        rt = Runtime(store=store or Store(":memory:"))
        block_info: dict[str, Any] = {}

        def _on_block(event: Any) -> None:
            block_info.setdefault("node", event.payload.get("blocked_node") or event.node_id)
            rt.submit(event.run_id, Intervention(action="abort"))

        rt.bus.on("run_blocked", _on_block)
        result = rt.run(self, inputs=inputs, run_id=run_id)
        if block_info:
            raise BlockedError(
                f"Process blocked on node {block_info.get('node')!r}. "
                "Use Runtime + control plane to intervene, or fix the cause."
            )
        return result.state

    def stream(
        self,
        inputs: dict[str, Any] | None = None,
        *,
        store: Any | None = None,
        run_id: str | None = None,
    ) -> Any:
        """Yield events as the process executes.

        Returns a generator. The run executes in a background thread; the
        generator terminates when the run terminates (completes, fails, or
        aborts).
        """
        import queue
        import threading

        from overseer.core.runtime import Intervention, Runtime
        from overseer.persistence.store import Store

        rt = Runtime(store=store or Store(":memory:"))
        q: queue.Queue = queue.Queue()
        sentinel = object()

        def _forward(event: Any) -> None:
            q.put(event)

        def _on_block(event: Any) -> None:
            rt.submit(event.run_id, Intervention(action="abort"))

        rt.bus.on_any(_forward)
        rt.bus.on("run_blocked", _on_block)

        def _worker() -> None:
            try:
                rt.run(self, inputs=inputs, run_id=run_id)
            except Exception as exc:
                q.put(("error", exc))
            finally:
                q.put(sentinel)

        threading.Thread(target=_worker, daemon=True).start()

        def _gen() -> Any:
            while True:
                item = q.get()
                if item is sentinel:
                    return
                if isinstance(item, tuple) and item and item[0] == "error":
                    raise item[1]
                yield item

        return _gen()

    def outgoing(self, node: str) -> list[Edge]:
        return [e for e in self.edges if e.source == node]

    def validate(self) -> GraphValidation:
        result = GraphValidation()
        if self.start_node is None:
            result.errors.append("No start node defined.")
            return result

        reachable = self._reachable_from(self.start_node)
        for name in self.nodes:
            if name not in reachable:
                result.warnings.append(f"Node {name!r} is unreachable from the start node.")
            if not self.outgoing(name):
                result.warnings.append(f"Node {name!r} has no outgoing edges (dead-end).")

        for edge in self.edges:
            if edge.source not in self.nodes:
                result.errors.append(f"Edge source {edge.source!r} is not a registered node.")
            if edge.target != TERMINAL and edge.target not in self.nodes:
                result.errors.append(f"Edge target {edge.target!r} is not a registered node.")

        for cycle_source, cycle_target in self._cycles():
            edge = next(
                (e for e in self.edges if e.source == cycle_source and e.target == cycle_target),
                None,
            )
            if edge and not (edge.policy and edge.policy.on_fail):
                result.warnings.append(
                    f"Cycle edge {cycle_source!r}→{cycle_target!r} has no retry policy; "
                    "the runtime will block on first failure without a bounded loop."
                )

        return result

    def topology(self) -> dict[str, Any]:
        """Serializable view of the graph for the UI."""
        return {
            "name": self.name,
            "start": self.start_node,
            "nodes": [
                {
                    "id": name,
                    "kind": node.kind,
                    "model": getattr(node, "model", None),
                    "idempotent": node.idempotent,
                }
                for name, node in self.nodes.items()
            ]
            + [{"id": TERMINAL, "kind": "terminal", "model": None, "idempotent": True}],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "condition": e.label(),
                    "has_policy": e.policy is not None,
                }
                for e in self.edges
            ],
        }

    def _reachable_from(self, start: str) -> set[str]:
        seen: set[str] = set()
        stack = [start]
        while stack:
            current = stack.pop()
            if current in seen or current == TERMINAL:
                continue
            seen.add(current)
            for edge in self.outgoing(current):
                stack.append(edge.target)
        return seen

    def _cycles(self) -> list[tuple[str, str]]:
        """Edges whose target is an ancestor of the source (back-edges)."""
        adj: dict[str, list[str]] = {n: [e.target for e in self.outgoing(n)] for n in self.nodes}
        adj.setdefault(TERMINAL, [])
        back: list[tuple[str, str]] = []
        color: dict[str, int] = {}  # 0 unvisited, 1 active, 2 done

        def dfs(node: str) -> None:
            color[node] = 1
            for nxt in adj.get(node, ()):
                state = color.get(nxt, 0)
                if state == 1:
                    back.append((node, nxt))
                elif state == 0:
                    dfs(nxt)
            color[node] = 2

        if self.start_node:
            dfs(self.start_node)
        return back
