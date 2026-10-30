"""Print one line each time boxes report new events, for Claude Code's Monitor tool.

Usage: watch.py [interval-seconds]
Polls the arbiter service at ARBITER_URL (default http://127.0.0.1:8700). Each
line names the tickets with new events, so the session knows to run
/arbiter:sync. Prints nothing while nothing happens, and never exits on its own.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

ARBITER_URL = os.environ.get("ARBITER_URL", "http://127.0.0.1:8700").rstrip("/")


def pending() -> list[dict]:
    with urllib.request.urlopen(f"{ARBITER_URL}/events", timeout=10) as resp:
        return json.loads(resp.read())["events"]


def main(argv: list[str]) -> int:
    interval = float(argv[0]) if argv else 5.0
    seen: set[int] = set()
    unreachable = False
    while True:
        try:
            events = pending()
        except (urllib.error.URLError, OSError, ValueError) as e:
            if not unreachable:
                print(f"arbiter: can't reach the service at {ARBITER_URL}: {e}", flush=True)
                unreachable = True
        else:
            if unreachable:
                print("arbiter: the service is reachable again", flush=True)
                unreachable = False
            new = [e for e in events if e["id"] not in seen]
            if new:
                tickets = sorted({f"{e['ticket']} {e['type']}" for e in new})
                print(f"arbiter: {len(new)} new event(s): {', '.join(tickets)}. Run /arbiter:sync.", flush=True)
            # Forget acked ids, so the set stays as small as the backlog.
            seen = {e["id"] for e in events}
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
