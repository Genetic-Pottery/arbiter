"""Maps each team to the box that hosts its session."""

import threading
import time
from typing import Callable


class Registry:
    """Team-to-box address book. An entry expires if its box stops heartbeating."""

    def __init__(self, ttl: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[str, str | None, float]] = {}

    def register(self, team: str, url: str, ticket: str | None = None) -> None:
        """Records that `url` serves `team`, working `ticket` if any. Calling it again counts as a heartbeat."""
        with self._lock:
            self._entries[team] = (url, ticket, self._clock())

    def lookup(self, team: str) -> str | None:
        """Returns the box URL for `team`, or None if no live box serves it."""
        with self._lock:
            entry = self._entries.get(team)
            if entry is None:
                return None
            url, _, seen = entry
            if self._clock() - seen > self._ttl:
                del self._entries[team]
                return None
            return url

    def teams(self) -> dict[str, dict[str, object]]:
        """Returns every live team with its box URL and the ticket it's working, if any."""
        with self._lock:
            now = self._clock()
            return {
                t: {"url": u, "busy": ticket is not None, "ticket": ticket}
                for t, (u, ticket, seen) in self._entries.items()
                if now - seen <= self._ttl
            }
