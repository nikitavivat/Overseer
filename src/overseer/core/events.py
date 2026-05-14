"""Single shared event bus. Runtime, persistence, and UI subscribe to it."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


EventType = str  # narrow strings used as event types — listed in EventTypes below


class EventTypes:
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_BLOCKED = "run_blocked"
    RUN_RESUMED = "run_resumed"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    NODE_BLOCKED = "node_blocked"
    VERIFIER_PASS = "verifier_pass"
    VERIFIER_FAIL = "verifier_fail"
    VERIFIER_RETRY = "verifier_retry"
    VERIFIER_ESCALATE = "verifier_escalate"
    USER_INTERVENTION = "user_intervention"
    SNAPSHOT_WRITTEN = "snapshot_written"


@dataclass
class Event:
    """Single append-only journal entry.

    `event_id` is unique. `parent_event_id` links to the prior event for the
    same node/run so the journal can be re-rendered as a tree.
    """

    run_id: str
    type: EventType
    node_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_event_id: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "node_id": self.node_id,
            "type": self.type,
            "payload": self.payload,
            "parent_event_id": self.parent_event_id,
            "timestamp": self.timestamp,
        }


Subscriber = Callable[[Event], None]


class EventBus:
    """Thread-safe synchronous event bus.

    Subscribers run inline. Slow subscribers slow the runtime — keep handlers
    cheap, or hand off to a queue inside the handler.
    """

    def __init__(self) -> None:
        self._typed: dict[str, list[Subscriber]] = defaultdict(list)
        self._wildcards: list[Subscriber] = []
        self._lock = threading.RLock()

    def on(self, event_type: EventType, callback: Subscriber) -> Callable[[], None]:
        with self._lock:
            self._typed[event_type].append(callback)
        return lambda: self._unsubscribe(event_type, callback)

    def on_any(self, callback: Subscriber) -> Callable[[], None]:
        with self._lock:
            self._wildcards.append(callback)
        return lambda: self._unsubscribe(None, callback)

    def emit(self, event: Event) -> None:
        with self._lock:
            typed = list(self._typed.get(event.type, ()))
            wildcards = list(self._wildcards)
        for cb in typed:
            self._safe_call(cb, event)
        for cb in wildcards:
            self._safe_call(cb, event)

    def _unsubscribe(self, event_type: EventType | None, callback: Subscriber) -> None:
        with self._lock:
            if event_type is None:
                if callback in self._wildcards:
                    self._wildcards.remove(callback)
            elif callback in self._typed.get(event_type, ()):
                self._typed[event_type].remove(callback)

    @staticmethod
    def _safe_call(callback: Subscriber, event: Event) -> None:
        try:
            callback(event)
        except Exception:
            log.exception("Event subscriber raised on %s (%s)", event.type, event.event_id)
