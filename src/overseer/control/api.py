"""FastAPI server: REST endpoints + WebSocket event stream.

This is the only thing the UI talks to. Keep the surface stable — the UI
contract is part of the public API.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from overseer.core.events import Event
from overseer.core.graph import Process
from overseer.core.runtime import Intervention, Runtime
from overseer.persistence.store import Store
from overseer.ui import STATIC_DIR

log = logging.getLogger(__name__)


class StartRunRequest(BaseModel):
    inputs: dict[str, Any] = {}


class InterventionRequest(BaseModel):
    action: str = "retry"  # "retry" | "skip" | "abort"
    node: str | None = None
    overrides: dict[str, Any] = {}


class ControlServer:
    """Holds the Process + Runtime + active run threads.

    A single Process is hot-loaded into the server. Multiple runs can execute
    in parallel — each in its own thread.
    """

    def __init__(self, process: Process, runtime: Runtime) -> None:
        self.process = process
        self.runtime = runtime
        self._threads: dict[str, threading.Thread] = {}
        self._broadcasters: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        runtime.bus.on_any(self._broadcast)

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _broadcast(self, event: Event) -> None:
        loop = self._loop
        if loop is None:
            return
        payload = event.to_dict()
        for queue_ in list(self._broadcasters):
            # RuntimeError fires if the loop closed during shutdown.
            with contextlib.suppress(RuntimeError):
                asyncio.run_coroutine_threadsafe(queue_.put(payload), loop)

    def start_run(self, inputs: dict[str, Any]) -> str:
        import uuid

        run_id = str(uuid.uuid4())

        def _target() -> None:
            try:
                self.runtime.run(self.process, inputs=inputs, run_id=run_id)
            except Exception:
                log.exception("Run %s crashed", run_id)

        thread = threading.Thread(target=_target, daemon=True, name=f"run-{run_id[:8]}")
        self._threads[run_id] = thread
        thread.start()
        return run_id

    def subscribe(self) -> asyncio.Queue:
        queue_: asyncio.Queue = asyncio.Queue()
        self._broadcasters.append(queue_)
        return queue_

    def unsubscribe(self, queue_: asyncio.Queue) -> None:
        if queue_ in self._broadcasters:
            self._broadcasters.remove(queue_)


def create_app(process: Process, store: Store | None = None) -> FastAPI:
    """Build the FastAPI app around an already-defined Process."""

    store = store or Store()
    runtime = Runtime(store=store)
    server = ControlServer(process=process, runtime=runtime)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        server.attach_loop(asyncio.get_running_loop())
        yield

    app = FastAPI(title="Overseer", version="0.1.0", lifespan=lifespan)
    app.state.server = server

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "process": process.name}

    @app.get("/api/graph")
    def graph() -> dict[str, Any]:
        return process.topology()

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        return store.list_runs()

    @app.post("/api/runs")
    def start_run(req: StartRunRequest) -> dict[str, str]:
        run_id = server.start_run(req.inputs)
        return {"run_id": run_id}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        run = store.get_run(run_id)
        if not run:
            raise HTTPException(404, "run not found")
        result = runtime.get_result(run_id)
        run["state"] = result.state if result else {}
        run["blocked_node"] = result.blocked_node if result else None
        return run

    @app.get("/api/runs/{run_id}/events")
    def get_events(run_id: str, after: float | None = None) -> list[dict[str, Any]]:
        return store.list_events(run_id, after=after)

    @app.get("/api/runs/{run_id}/snapshots")
    def get_snapshots(run_id: str) -> list[dict[str, Any]]:
        return [
            {
                "snapshot_id": s.snapshot_id,
                "node_id": s.node_id,
                "timestamp": s.timestamp,
                "data": s.data,
            }
            for s in store.list_snapshots(run_id)
        ]

    @app.post("/api/runs/{run_id}/intervene")
    def intervene(run_id: str, req: InterventionRequest) -> dict[str, str]:
        try:
            server.runtime.submit(
                run_id,
                Intervention(action=req.action, node=req.node, overrides=req.overrides),
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"status": "submitted"}

    @app.websocket("/api/stream")
    async def stream(ws: WebSocket) -> None:
        await ws.accept()
        queue_ = server.subscribe()
        try:
            while True:
                payload = await queue_.get()
                await ws.send_json(payload)
        except WebSocketDisconnect:
            pass
        finally:
            server.unsubscribe(queue_)

    # UI static files
    static = StaticFiles(directory=str(STATIC_DIR), html=False)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(STATIC_DIR / "index.html"))

    app.mount("/static", static, name="static")

    @app.exception_handler(ValueError)
    async def value_error_handler(_request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app
