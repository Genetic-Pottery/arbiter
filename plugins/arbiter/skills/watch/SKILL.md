---
name: watch
description: Keep the arbiter running on its own. Watch for events from the boxes and for merged pull requests, and run /arbiter:sync whenever one arrives. Use when the arbiter session starts, or when the person wants work to keep moving without asking.
---

Start a watch, so boxes' reports reach the tracker, their questions reach the
person, and merged pull requests unblock the next tickets, without anyone
running `/arbiter:sync` by hand.

1. Run `/arbiter:sync` once, to clear anything that arrived before the watch.
2. Start the Monitor tool with:
   - command: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/watch.py"`
   - description: `arbiter events`
   - timeout_ms: `1800000`, the longest a monitor runs

   The script prints a line only when boxes report new events or a pull
   request labeled `warlock` merges, so a quiet watch costs nothing. It checks
   for merges with `gh` in the working directory's repository once a minute.
3. Reply in one line: the watch is on, and you'll sync when boxes report.

When a monitor line arrives:

- A line naming new events or merged pull requests: run `/arbiter:sync`. Then go back to waiting. If
  sync brings a question to the person, ask it, and leave the watch running.
- A line saying the service is unreachable: tell the person once. The script
  keeps retrying and says when the service is back.
- A line saying it can't check for merges: tell the person once. Events still
  arrive, and merged tickets wait for the next sync.

When the monitor expires, start it again with the same command, then run
`/arbiter:sync` once in case an event arrived between the two monitors.

If the Monitor tool isn't available, say so, and suggest
`/loop 5m /arbiter:sync` instead.
