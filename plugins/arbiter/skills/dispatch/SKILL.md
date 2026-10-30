---
name: dispatch
description: Send the next unblocked ticket of each idle team to that team's box. Use after /warlock:draft files tickets, after /arbiter:sync, or when the person asks to start work.
argument-hint: "[team key | ticket key]"
---

Hand tickets to the boxes. You read the tracker; the boxes never do. Each box
gets everything it needs in the ticket payload, works it with `/worker:work`,
and reports back as events that `/arbiter:sync` writes to the tracker.

For tracker steps, read `${CLAUDE_PLUGIN_ROOT}/reference/trackers.md`.

## 1. Read the scopes

Read `.warlock/scopes.toml` in the working directory. If it's missing, stop and
say that the arbiter session must run in a repository set up with
`/warlock:init`.

For each `[[scope]]` that isn't `shared`, note its `name`, `tracker`, and
`team`, and these settings. A scope's own value wins over the top-level value,
and a missing setting takes the default:

| Setting | Default |
|---|---|
| `base` | `main` |
| `label` | `warlock` |
| `start_state` | `In Progress` |
| `review_state` | `In Review` |
| `project_review_state` | `In Review` |

`project_branches` is top-level only, default `false`.

## 2. Find idle teams

Call the `list_teams` tool. A box registers each team under the team key, so
match boxes to scopes by `team`. A team is ready when a box serves it and
`busy` is false. Judge each team on its own: one box can serve several teams,
and they work their tickets in parallel, so another team's busy ticket on the
same box doesn't matter.

With a team key in `$ARGUMENTS`, consider only that team. With a ticket key,
consider only that ticket's team, and take that ticket in step 3.

If no team is ready, say which teams are busy and which have no box, then stop.

## 3. Pick a ticket per ready team

For each ready team, read:

1. tickets in `start_state` that are assigned to you, carry `label`, and have a
   comment starting `Warlock plan`. These are paused or interrupted runs; take
   the first.
2. the queue (see "The queue" in the tracker reference). Take the first ticket.

In both lists, skip a ticket whose newest comment starting `Warlock` is a
`Warlock halted:` comment. Taken by key, a halted ticket resumes like any other.

If both lists are empty, the team has nothing to do.

## 4. Dispatch

For each picked ticket:

1. Pick the target. When `project_branches` is true and the description has a
   `## Project branch` section, the target is the branch named there.
   Otherwise the target is `base`.
2. Read every comment on the ticket, oldest first.
3. Call the `dispatch` tool with the team key and a ticket holding `key`,
   `title`, `url`, the full `description`, every comment as
   `{author, body}`, `target`, `scope` (the scope's name), and `test_plan` when
   the description has one. Leave nothing out: the box can't read the tracker.
4. If `dispatch` succeeds, move the ticket to `start_state`. If it fails with
   409, the team took other work meanwhile: skip it.

If a tracker step fails, retry it once. If it fails again, stop and say which
step failed. Don't dispatch a ticket you couldn't read in full: a box working
from a partial ticket can't ask for the rest.

## 5. Reply

One line per team: the ticket dispatched, or why none was. Say that
`/arbiter:sync` records what the boxes report.
