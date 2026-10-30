"""Events that boxes report while they work a ticket, held until the arbiter session acks them."""

import json
import threading
import time
from pathlib import Path
from typing import Any

# plan, progress, paused, halted, and done come from the worker plugin.
# exited comes from the box when the Claude process ends, whatever the reason.
TYPES = ("plan", "progress", "paused", "halted", "done", "exited")


class EventLog:
    """Ordered events with at-least-once delivery. With a path, they survive a restart."""

    def __init__(self, path: Path | None = None):
        self._path = path
        self._lock = threading.Lock()
        self._events: dict[int, dict[str, Any]] = {}
        self._next = 1
        if path is not None and path.exists():
            self._replay(path)

    def _replay(self, path: Path) -> None:
        for line in path.read_text().splitlines():
            record = json.loads(line)
            if record["op"] == "event":
                event = record["event"]
                self._events[event["id"]] = event
                self._next = max(self._next, event["id"] + 1)
            elif record["op"] == "ack":
                for id_ in record["ids"]:
                    self._events.pop(id_, None)

    def _write(self, record: dict[str, Any]) -> None:
        if self._path is not None:
            with self._path.open("a") as f:
                f.write(json.dumps(record) + "\n")

    def append(self, team: str, ticket: str, type_: str, body: str = "") -> dict[str, Any]:
        if type_ not in TYPES:
            raise ValueError(f"unknown event type {type_!r}; expected one of {', '.join(TYPES)}")
        with self._lock:
            event = {"id": self._next, "time": time.time(), "team": team, "ticket": ticket, "type": type_, "body": body}
            self._next += 1
            self._events[event["id"]] = event
            self._write({"op": "event", "event": event})
            return event

    def pending(self) -> list[dict[str, Any]]:
        """Returns every event not yet acked, oldest first."""
        with self._lock:
            return [self._events[i] for i in sorted(self._events)]

    def ack(self, ids: list[int]) -> None:
        with self._lock:
            for id_ in ids:
                self._events.pop(id_, None)
            self._write({"op": "ack", "ids": ids})
