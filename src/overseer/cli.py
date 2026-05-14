"""Command-line entry point: `overseer run|serve|replay`."""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import threading
import time
import webbrowser
from pathlib import Path

import click
import uvicorn

from overseer.control.api import create_app
from overseer.core.graph import Process
from overseer.persistence.store import Store

log = logging.getLogger(__name__)


def _load_process(file: str) -> Process:
    """Import a Python file and return its `process` global."""
    path = Path(file).resolve()
    if not path.exists():
        raise click.ClickException(f"File not found: {file}")
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    if spec is None or spec.loader is None:
        raise click.ClickException(f"Cannot load {file} as a Python module")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(module)

    candidate = getattr(module, "process", None)
    if candidate is None:
        for value in vars(module).values():
            if isinstance(value, Process):
                candidate = value
                break
    if not isinstance(candidate, Process):
        raise click.ClickException(
            f"{file} does not expose a `process` variable of type overseer.Process"
        )
    return candidate


@click.group()
@click.version_option(package_name="overseer-ai")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def cli(verbose: bool) -> None:
    """Overseer — reliable multi-agent AI processes."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@cli.command()
@click.argument("file")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", type=int, default=8765, show_default=True)
@click.option("--db", default="overseer.db", show_default=True, help="SQLite store path.")
@click.option("--open/--no-open", "open_browser", default=True, help="Open the UI in a browser.")
@click.option(
    "--auto-start/--no-auto-start",
    default=True,
    help="Kick off a run automatically once the server is up.",
)
@click.option(
    "--task",
    default="Investigate a topic and produce a brief report.",
    help="Initial `task` input passed to the auto-started run.",
)
def run(
    file: str, host: str, port: int, db: str, open_browser: bool, auto_start: bool, task: str
) -> None:
    """Load a process file, start the server, optionally fire a run."""
    process = _load_process(file)
    click.secho(
        f"[Overseer] loaded process {process.name!r} "
        f"({len(process.nodes)} nodes, {len(process.edges)} edges)",
        fg="cyan",
    )
    store = Store(db)
    app = create_app(process, store=store)

    if auto_start:
        def _kick() -> None:
            import urllib.error
            import urllib.request

            time.sleep(0.6)
            url = f"http://{host}:{port}/api/runs"
            payload = json.dumps({"inputs": {"task": task}}).encode()
            req = urllib.request.Request(
                url, data=payload, headers={"content-type": "application/json"}, method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=5):
                    pass
            except (urllib.error.URLError, TimeoutError) as exc:
                log.warning("auto-start failed: %s (use the UI Start button)", exc)

        threading.Thread(target=_kick, daemon=True).start()

    if open_browser:
        threading.Thread(
            target=lambda: (time.sleep(0.4), webbrowser.open(f"http://{host}:{port}")),
            daemon=True,
        ).start()

    click.secho(f"[Overseer] http://{host}:{port}", fg="green")
    uvicorn.run(app, host=host, port=port, log_level="warning")


@cli.command()
@click.argument("file")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", type=int, default=8765, show_default=True)
@click.option("--db", default="overseer.db", show_default=True)
def serve(file: str, host: str, port: int, db: str) -> None:
    """Serve the UI without auto-starting a run."""
    process = _load_process(file)
    store = Store(db)
    app = create_app(process, store=store)
    click.secho(f"[Overseer] http://{host}:{port}", fg="green")
    uvicorn.run(app, host=host, port=port, log_level="warning")


@cli.command()
@click.argument("snapshot_id")
@click.option("--db", default="overseer.db", show_default=True)
def replay(snapshot_id: str, db: str) -> None:
    """Print a stored snapshot. Full replay lands in v0.2."""
    store = Store(db)
    snap = store.get_snapshot(snapshot_id)
    if snap is None:
        raise click.ClickException(f"No snapshot {snapshot_id!r} in {db}")
    click.echo(
        json.dumps(
            {
                "snapshot_id": snap.snapshot_id,
                "run_id": snap.run_id,
                "node_id": snap.node_id,
                "timestamp": snap.timestamp,
                "data": snap.data,
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    cli()
