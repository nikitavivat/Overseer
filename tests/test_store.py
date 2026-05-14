"""Persistence: events and snapshots round-trip cleanly."""

from __future__ import annotations

from overseer.core.events import Event
from overseer.persistence.store import Store


def test_record_and_get_run(tmp_store: Store):
    tmp_store.record_run(run_id="r1", process_name="p")
    run = tmp_store.get_run("r1")
    assert run is not None
    assert run["process_name"] == "p"
    assert run["status"] == "running"


def test_update_run_status(tmp_store: Store):
    tmp_store.record_run(run_id="r1", process_name="p")
    tmp_store.update_run("r1", status="completed", ended_at=1234.5)
    run = tmp_store.get_run("r1")
    assert run["status"] == "completed"
    assert run["ended_at"] == 1234.5


def test_event_round_trip(tmp_store: Store):
    tmp_store.record_run(run_id="r1", process_name="p")
    e = Event(run_id="r1", type="node_started", node_id="a", payload={"x": 1})
    tmp_store.append_event(e)
    events = tmp_store.list_events("r1")
    assert len(events) == 1
    assert events[0]["event_id"] == e.event_id
    assert events[0]["payload"] == {"x": 1}


def test_event_after_filter(tmp_store: Store):
    tmp_store.record_run(run_id="r1", process_name="p")
    e1 = Event(run_id="r1", type="t", payload={}, timestamp=100.0)
    e2 = Event(run_id="r1", type="t", payload={}, timestamp=200.0)
    tmp_store.append_event(e1)
    tmp_store.append_event(e2)
    after = tmp_store.list_events("r1", after=150.0)
    assert [x["event_id"] for x in after] == [e2.event_id]


def test_snapshot_round_trip(tmp_store: Store):
    tmp_store.record_run(run_id="r1", process_name="p")
    sid = tmp_store.put_snapshot(run_id="r1", node_id="n", data={"k": "v"})
    snap = tmp_store.get_snapshot(sid)
    assert snap is not None
    assert snap.data == {"k": "v"}


def test_latest_snapshot(tmp_store: Store):
    tmp_store.record_run(run_id="r1", process_name="p")
    tmp_store.put_snapshot(run_id="r1", node_id="n", data={"v": 1})
    tmp_store.put_snapshot(run_id="r1", node_id="n", data={"v": 2})
    latest = tmp_store.latest_snapshot("r1", "n")
    assert latest is not None
    assert latest.data == {"v": 2}
