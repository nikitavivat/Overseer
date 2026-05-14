"""SQLite-backed event journal and snapshot store.

The journal is append-only. Snapshots are JSON blobs keyed by `snapshot_id`.
Both schemas are deliberately open so anyone can `sqlite3 overseer.db` and
inspect — there is no proprietary format.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from overseer.core.events import Event

DEFAULT_PATH = "overseer.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    process_name  TEXT NOT NULL,
    status        TEXT NOT NULL,
    started_at    REAL NOT NULL,
    ended_at      REAL
);

CREATE TABLE IF NOT EXISTS events (
    event_id        TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    node_id         TEXT,
    type            TEXT NOT NULL,
    payload         TEXT NOT NULL,
    parent_event_id TEXT,
    timestamp       REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_run_ts ON events(run_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_node ON events(run_id, node_id, timestamp);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id  TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,
    node_id      TEXT NOT NULL,
    data         TEXT NOT NULL,
    timestamp    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_run ON snapshots(run_id, timestamp);
"""


@dataclass
class Snapshot:
    snapshot_id: str
    run_id: str
    node_id: str
    data: dict[str, Any]
    timestamp: float


class Store:
    """Thread-safe SQLite store. One connection, serialized via a lock."""

    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.executescript(SCHEMA)

    # ---------- runs ----------

    def record_run(self, *, run_id: str, process_name: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO runs (run_id, process_name, status, started_at) "
                "VALUES (?, ?, ?, ?)",
                (run_id, process_name, "running", time.time()),
            )

    def update_run(self, run_id: str, *, status: str, ended_at: float | None = None) -> None:
        with self._lock:
            if ended_at is not None:
                self._conn.execute(
                    "UPDATE runs SET status = ?, ended_at = ? WHERE run_id = ?",
                    (status, ended_at, run_id),
                )
            else:
                self._conn.execute(
                    "UPDATE runs SET status = ? WHERE run_id = ?", (status, run_id)
                )

    def list_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id, process_name, status, started_at, ended_at "
                "FROM runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "run_id": r[0],
                "process_name": r[1],
                "status": r[2],
                "started_at": r[3],
                "ended_at": r[4],
            }
            for r in rows
        ]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT run_id, process_name, status, started_at, ended_at "
                "FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row[0],
            "process_name": row[1],
            "status": row[2],
            "started_at": row[3],
            "ended_at": row[4],
        }

    # ---------- events ----------

    def append_event(self, event: Event) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events "
                "(event_id, run_id, node_id, type, payload, parent_event_id, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.run_id,
                    event.node_id,
                    event.type,
                    json.dumps(event.payload, default=str),
                    event.parent_event_id,
                    event.timestamp,
                ),
            )

    def list_events(self, run_id: str, *, after: float | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if after is None:
                rows = self._conn.execute(
                    "SELECT event_id, run_id, node_id, type, payload, parent_event_id, timestamp "
                    "FROM events WHERE run_id = ? ORDER BY timestamp",
                    (run_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT event_id, run_id, node_id, type, payload, parent_event_id, timestamp "
                    "FROM events WHERE run_id = ? AND timestamp > ? ORDER BY timestamp",
                    (run_id, after),
                ).fetchall()
        return [_row_to_event(r) for r in rows]

    # ---------- snapshots ----------

    def put_snapshot(self, *, run_id: str, node_id: str, data: dict[str, Any]) -> str:
        snapshot_id = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                "INSERT INTO snapshots (snapshot_id, run_id, node_id, data, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (snapshot_id, run_id, node_id, json.dumps(data, default=str), time.time()),
            )
        return snapshot_id

    def get_snapshot(self, snapshot_id: str) -> Snapshot | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT snapshot_id, run_id, node_id, data, timestamp "
                "FROM snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        return Snapshot(
            snapshot_id=row[0],
            run_id=row[1],
            node_id=row[2],
            data=json.loads(row[3]),
            timestamp=row[4],
        )

    def list_snapshots(self, run_id: str) -> list[Snapshot]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT snapshot_id, run_id, node_id, data, timestamp "
                "FROM snapshots WHERE run_id = ? ORDER BY timestamp",
                (run_id,),
            ).fetchall()
        return [
            Snapshot(
                snapshot_id=r[0],
                run_id=r[1],
                node_id=r[2],
                data=json.loads(r[3]),
                timestamp=r[4],
            )
            for r in rows
        ]

    def latest_snapshot(self, run_id: str, node_id: str) -> Snapshot | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT snapshot_id, run_id, node_id, data, timestamp "
                "FROM snapshots WHERE run_id = ? AND node_id = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (run_id, node_id),
            ).fetchone()
        if row is None:
            return None
        return Snapshot(
            snapshot_id=row[0],
            run_id=row[1],
            node_id=row[2],
            data=json.loads(row[3]),
            timestamp=row[4],
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _row_to_event(row: tuple) -> dict[str, Any]:
    return {
        "event_id": row[0],
        "run_id": row[1],
        "node_id": row[2],
        "type": row[3],
        "payload": json.loads(row[4]) if row[4] else {},
        "parent_event_id": row[5],
        "timestamp": row[6],
    }
