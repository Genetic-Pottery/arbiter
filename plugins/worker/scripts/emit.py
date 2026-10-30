"""Report a worker event to the arbiter.

Usage: emit.py <type> [body]
Reads the body from stdin when it's omitted or `-`. The box sets ARBITER_EVENTS_URL,
ARBITER_TEAM, and ARBITER_TICKET for the run.
"""

import json
import os
import sys
import urllib.error
import urllib.request

TYPES = ("plan", "progress", "paused", "halted", "done")


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in TYPES:
        print(f"usage: emit.py {{{'|'.join(TYPES)}}} [body]", file=sys.stderr)
        return 2
    missing = [v for v in ("ARBITER_EVENTS_URL", "ARBITER_TEAM", "ARBITER_TICKET") if not os.environ.get(v)]
    if missing:
        print(f"emit: not running under an arbiter box ({', '.join(missing)} unset)", file=sys.stderr)
        return 1
    body = sys.stdin.read() if len(argv) < 2 or argv[1] == "-" else argv[1]
    event = {
        "team": os.environ["ARBITER_TEAM"],
        "ticket": os.environ["ARBITER_TICKET"],
        "type": argv[0],
        "body": body,
    }
    req = urllib.request.Request(
        os.environ["ARBITER_EVENTS_URL"],
        data=json.dumps(event).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"emitted {argv[0]} as event {json.loads(resp.read())['id']}")
    except (urllib.error.URLError, OSError) as e:
        print(f"emit: can't reach the arbiter: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
