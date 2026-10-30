---
name: sync
description: Write what the boxes reported to the tracker, bring their questions to the person, and dispatch the next tickets. Use when the person asks how work is going, or on a loop.
---

The boxes have no tracker access. They report events, and you write each one to
its ticket. The tracker stays the record: a later run resumes from the comments
you write here.

For tracker steps, read `${CLAUDE_PLUGIN_ROOT}/reference/trackers.md`. Read the
scope settings from `.warlock/scopes.toml` as `/arbiter:dispatch` describes:
the scope is the one whose `team` matches the event's `team`.

## 1. Handle events

Call the `events` tool. Handle the events oldest first. After each event's
tracker update succeeds, call `ack` with its id. If an update fails, retry it
once. If it fails again, stop without acking it, and say what failed: the next
sync retries it.

| Event | What to do |
|---|---|
| `plan` | Comment the body on the ticket. |
| `progress` | Edit the ticket's newest comment starting `Warlock plan` to the body. If you can't edit it, comment the body. |
| `done` | Comment the body. Move the ticket to `review_state`. If the ticket belongs to a project or epic and every ticket in it is now in `review_state` or finished, move the project or epic to `project_review_state`. |
| `paused` | Comment the body. Leave the ticket in `start_state`. |
| `halted` | Comment the body. Move the ticket back to an unstarted state. Keep the ticket for step 4. |
| `exited` | See below. |

An `exited` event means the run's process ended. Its body is JSON with
`returncode` and `tail`, the end of the run's output. Look at the events for
the same ticket in this batch and on the ticket's comments since the last
`Warlock plan`:

- If the run reported `done`, `paused`, or `halted`, ack it and do nothing more.
- Otherwise the run died without a word. Pause it as "Pause a lost run"
  describes, with the reason
  `the run ended without reporting an outcome (exit <returncode>)`, followed by
  the last lines of `tail`.

## 2. Find lost runs

A box that's destroyed, rebooted, or cut off mid-run never reports `exited`.
Its ticket stays in `start_state` with no outcome. Find these after step 1, so
every reported outcome is already on its ticket.

Call `list_teams` and note each team's `ticket`. Then, for each non-shared
scope, list the tickets in `start_state` that carry `label` and are assigned to
you. A ticket is lost when all of these hold:

- its newest comment starting `Warlock` is a `Warlock plan` comment, or it has
  no comment starting `Warlock`
- no team in `list_teams` reports it as its `ticket`
- `events` returns no unacked event for it

For each lost ticket, pause it as "Pause a lost run" describes. Name the
reason by what `list_teams` shows for the ticket's team:

- the team is missing: `no live box serves <team>; the box was removed or stopped heartbeating`
- the team is idle or working another ticket: `the box lost the run, for example in a restart`

A ticket moved to `start_state` by `/arbiter:dispatch` a moment ago might not
show on its team yet. Call `list_teams` again before pausing, and skip a ticket
that appears.

### Pause a lost run

1. If the ticket's newest two comments starting `Warlock` are both
   `Warlock paused:`, this is the third in a row. Comment `Warlock halted:` with
   the three reasons, move the ticket to an unstarted state, and keep it for
   step 4.
2. Otherwise comment `Warlock paused:` and the reason. Say that the next
   dispatch resumes from the plan comment, or starts over when there's none.
   Leave the ticket in `start_state`.

## 3. Finish merged tickets

A ticket in `review_state` waits on a person to merge its pull request. A
`blocked by` link counts only a finished ticket, so until the merged ticket
moves on, the tickets it blocks stay out of the queue. Some trackers move a
ticket when its pull request merges, but not into a project branch, and not
without their GitHub integration. Move it here.

For each non-shared scope, list the tickets in `review_state` that carry
`label` and are assigned to you. For each, find the pull request: the first
line of the newest comment that holds a pull request URL. Run
`gh pr view <url> --json state`:

- `MERGED`: move the ticket to a finished state, Linear's `completed` type or
  Jira's status category Done. If its project or epic has every ticket
  finished, leave the project or epic as it is and tell the person: a project
  branch still needs its own pull request into `base`.
- `CLOSED`: leave the ticket, and tell the person the pull request closed
  without merging.
- `OPEN`, or no pull request found: leave the ticket.

If `gh` fails, say so and go on: the next sync checks again.

## 4. Bring questions to the person

For each halted ticket, tell the person the ticket key, title, link, and the
reason. The link is the ticket's tracker URL, not the repository. When the body
has a line starting `Question:`, ask that question in plain words.

When the person answers:

1. Comment the answer on the ticket as a plain comment, not starting `Warlock`.
2. When the answer changes or adds a requirement, record it in the ticket's
   description too, so the description stays true for whoever reads it next.
   Add a line to a `## Decisions` section at the end of the description,
   creating the section if it's missing: the decision in one sentence, and the
   date. Leave the rest of the description as it is.
3. Run `/arbiter:dispatch <ticket key>` so the box resumes with the answer.

## 5. Dispatch

Run `/arbiter:dispatch`, so idle teams take their next tickets. A ticket
finished in step 3 may have unblocked another ticket.

## 6. Reply

Lead with the questions from step 4, if any. Then one line per ticket that
changed: key, what happened, and the pull request link for `done`. Link a
ticket with its tracker URL. If nothing happened, say so in one line.
