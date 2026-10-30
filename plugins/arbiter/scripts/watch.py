"""Print one line each time there's something to sync, for Claude Code's Monitor tool.

Usage: watch.py [interval-seconds [merge-interval-seconds]]
Polls the arbiter service at ARBITER_URL (default http://127.0.0.1:8700) for
events the boxes report, and the current directory's GitHub repository for
pull requests labeled `warlock` that merged since the watch started. A merge
can unblock tickets, so it needs a sync as much as an event does. Each line
names what happened, so the session knows to run /arbiter:sync. Prints nothing
while nothing happens, and never exits on its own.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ARBITER_URL = os.environ.get("ARBITER_URL", "http://127.0.0.1:8700").rstrip("/")


def pending() -> list[dict]:
    with urllib.request.urlopen(f"{ARBITER_URL}/events", timeout=10) as resp:
        return json.loads(resp.read())["events"]


def merged() -> list[dict]:
    out = subprocess.run(
        ["gh", "pr", "list", "--state", "merged", "--label", "warlock",
         "--json", "number,title,mergedAt", "--limit", "30"],
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    return json.loads(out)


def main(argv: list[str]) -> int:
    interval = float(argv[0]) if argv else 5.0
    merge_interval = float(argv[1]) if len(argv) > 1 else 60.0
    seen: set[int] = set()
    unreachable = False
    # GitHub's timestamps are UTC ISO 8601, so they compare as strings.
    merged_after = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    merges_seen: set[int] = set()
    merges_broken = False
    next_merge_check = 0.0
    while True:
        if time.monotonic() >= next_merge_check:
            next_merge_check = time.monotonic() + merge_interval
            try:
                prs = merged()
            except (OSError, subprocess.SubprocessError, ValueError) as e:
                if not merges_broken:
                    print(f"arbiter: can't check for merged pull requests with gh: {e}", flush=True)
                    merges_broken = True
            else:
                merges_broken = False
                new = [pr for pr in prs if pr["mergedAt"] > merged_after and pr["number"] not in merges_seen]
                if new:
                    merges_seen.update(pr["number"] for pr in new)
                    names = ", ".join(f"#{pr['number']} {pr['title']}" for pr in sorted(new, key=lambda pr: pr["number"]))
                    print(f"arbiter: pull request(s) merged: {names}. Run /arbiter:sync.", flush=True)
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
