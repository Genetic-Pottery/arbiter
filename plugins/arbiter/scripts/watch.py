"""Print one line each time there's something to sync, for Claude Code's Monitor tool.

Usage: watch.py [interval-seconds [merge-interval-seconds]]
Polls the arbiter service at ARBITER_URL (default http://127.0.0.1:8700) for
events the boxes report, and each repository checkout for pull requests that
merged since the watch started: those labeled `warlock`, and those from a
project branch, a branch warlock pull requests target. A ticket's merge can
unblock tickets, and a project branch's merge finishes its project, so each
needs a sync as much as an event does.

The checkouts are the current directory when it holds .warlock/scopes.toml,
and otherwise each directory in it that does. Each line names what happened,
so the session knows to run /arbiter:sync. Prints nothing while nothing
happens, and never exits on its own.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ARBITER_URL = os.environ.get("ARBITER_URL", "http://127.0.0.1:8700").rstrip("/")


def pending() -> list[dict]:
    with urllib.request.urlopen(f"{ARBITER_URL}/events", timeout=10) as resp:
        return json.loads(resp.read())["events"]


def checkouts(root: Path) -> list[Path]:
    """Returns the repository checkouts the arbiter session works with."""
    if (root / ".warlock" / "scopes.toml").is_file():
        return [root]
    return sorted(d for d in root.iterdir() if (d / ".warlock" / "scopes.toml").is_file())


def merged(checkout: Path) -> list[dict]:
    """Returns the checkout's merged pull requests labeled `warlock` or opened from a project branch."""
    out = subprocess.run(
        ["gh", "pr", "list", "--state", "all", "--limit", "100",
         "--json", "number,title,mergedAt,headRefName,baseRefName,labels"],
        cwd=checkout, capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    prs = json.loads(out)
    ticket_prs = [pr for pr in prs if any(label["name"] == "warlock" for label in pr["labels"])]
    project_branches = {pr["baseRefName"] for pr in ticket_prs}
    return [
        pr for pr in prs
        if pr.get("mergedAt") and (pr in ticket_prs or pr["headRefName"] in project_branches)
    ]


def main(argv: list[str]) -> int:
    interval = float(argv[0]) if argv else 5.0
    merge_interval = float(argv[1]) if len(argv) > 1 else 60.0
    seen: set[int] = set()
    unreachable = False
    # GitHub's timestamps are UTC ISO 8601, so they compare as strings.
    merged_after = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    merges_seen: set[tuple[str, int]] = set()
    merges_broken = False
    next_merge_check = 0.0
    while True:
        if time.monotonic() >= next_merge_check:
            next_merge_check = time.monotonic() + merge_interval
            try:
                found = checkouts(Path.cwd())
                if not found:
                    raise ValueError(f"no repository checkout with .warlock/scopes.toml in {Path.cwd()}")
                prs = [(c.name, pr) for c in found for pr in merged(c)]
            except (OSError, subprocess.SubprocessError, ValueError) as e:
                if not merges_broken:
                    print(f"arbiter: can't check for merged pull requests with gh: {e}", flush=True)
                    merges_broken = True
            else:
                merges_broken = False
                new = [(name, pr) for name, pr in prs
                       if pr["mergedAt"] > merged_after and (name, pr["number"]) not in merges_seen]
                if new:
                    merges_seen.update((name, pr["number"]) for name, pr in new)
                    names = ", ".join(f"{name}#{pr['number']} {pr['title']}"
                                      for name, pr in sorted(new, key=lambda np: (np[0], np[1]["number"])))
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
