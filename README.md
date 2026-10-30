# arbiter

Arbiter is one front door for a team of Claude boxes. You talk to one Claude
session, the *arbiter session*, from the Claude app. It turns your requests
into tracker tickets with [Warlock](https://github.com/Genetic-Pottery/warlock),
hands each ticket to the box that owns its team, and writes what the boxes
report back to the tracker.

Only the arbiter session touches the tracker. Boxes get each ticket's full
contents in the dispatch, and report progress as events. A box needs a model
and GitHub access, nothing else: no claude.ai login and no tracker keys.

```
you (Claude app) ─> arbiter session ──> Linear / Jira
                         │  arbiter plugin (MCP tools)
                         v
                  arbiter service ──(registry: team → box)──> box ──> claude -p "/worker:work"
                         ^                                           │
                         └──────────── events (plan, done, ...) ─────┘
```

## Parts

This repository holds three parts:

- **The arbiter service** (`python3 -m arbiter serve`) keeps the registry of
  which box serves each team, forwards dispatches, and holds the events boxes
  report until the arbiter session acks them.
- **The box agent** (`python3 -m arbiter box`) runs on each box. It registers
  its teams, and for each dispatch runs `claude -p "/worker:work <payload>"` in
  the team's working directory. A team works one ticket at a time.
- **Two Claude Code plugins**, in one marketplace:
  - `arbiter`, for the arbiter session. It adds the MCP tools `list_teams`,
    `dispatch`, `events`, `ack`, and `send`, and the skills `/arbiter:dispatch`,
    `/arbiter:sync`, and `/arbiter:watch`.
  - `worker`, for boxes. Its `/worker:work` skill takes a ticket to a pull
    request the way `/warlock:pull` does, but reports every step as an event
    instead of writing to the tracker.

The Python code uses only the standard library. It needs Python 3.10 or later.

## How a ticket moves

1. You describe the work. The arbiter session runs `/warlock:brief` and
   `/warlock:draft`, which file one ticket per team with `blocked by` links.
2. `/arbiter:dispatch` picks the next unblocked ticket for each idle team, reads
   it and every comment, and sends it to the team's box.
3. The box plans, works the sub-tasks, and opens a pull request. It reports
   `plan`, `progress`, and one of `done`, `paused`, or `halted`. When the run's
   process ends, the box reports `exited`.
4. `/arbiter:sync` writes each event to its ticket as the same `Warlock`
   comments `/warlock:pull` writes, moves the ticket, and asks you any question
   a halted ticket raises. Then it dispatches the tickets that are now
   unblocked.

Sync also catches runs that never finish:

- A run that dies without reporting an outcome shows up as an `exited` event
  with no `done`, `paused`, or `halted` before it.
- A box that's destroyed or cut off mid-run sends nothing at all. Each
  heartbeat names the ticket each team is working, so sync finds a started
  ticket that no live box claims.

Sync comments either case as a pause, and the next dispatch resumes from the
plan comment. Three pauses in a row halt the ticket.

## Run it locally

1. Start the arbiter service:

   ```sh
   python3 -m arbiter serve --events-file ~/.arbiter/events.jsonl
   ```

2. Start a box. Name each team by its tracker key, the prefix on its ticket
   numbers, and point it at a clone of the repository:

   ```sh
   python3 -m arbiter box \
     --team DB=~/work/app --team UI=~/work/app-ui \
     --claude-args "--plugin-dir ~/src/arbiter/plugins/worker --permission-mode acceptEdits --allowedTools Read Grep Glob Agent Bash(git:*) Bash(gh:*) Bash(python3:*)"
   ```

   The box runs Claude headless, so `--claude-args` must allow every tool the
   work needs. Add your test runner to `--allowedTools`. Give each team its own
   clone: a team's run switches branches in its working directory.

3. Start the arbiter session in a repository set up with `/warlock:init`, with
   both plugins loaded:

   ```sh
   claude --plugin-dir ~/src/warlock --plugin-dir ~/src/arbiter/plugins/arbiter
   ```

   To drive it from the Claude app, start it with Remote Control.

4. Run `/arbiter:watch`. It starts a background monitor that wakes the session
   whenever a box reports, and runs `/arbiter:sync`. Without it, run
   `/arbiter:sync` yourself, or use `/loop 5m /arbiter:sync`.
5. Ask for work.

To check the service from a terminal, run `python3 -m arbiter teams` or
`python3 -m arbiter events`.

## Deploy

To run arbiter on AWS, with an arbiter box you reach from the Claude app and
worker boxes on Bedrock, see [deploy/README.md](deploy/README.md).

## HTTP API

The arbiter service listens on port 8700 by default.

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/register` | `{team, url, ticket}` | `{ok}`. Boxes call it as a heartbeat, with the ticket the team is working or `null`. |
| `GET` | `/teams` | | `{teams: {team: {url, busy, ticket}}}` |
| `POST` | `/dispatch` | `{team, ticket}` | `{ok}`, `404` if no live box serves the team, or `409` if the team is busy. |
| `POST` | `/events` | `{team, ticket, type, body}` | `{id}` |
| `GET` | `/events` | | `{events: [...]}`, every unacked event, oldest first. |
| `POST` | `/events/ack` | `{ids}` | `{ok}` |
| `POST` | `/message` | `{team, speaker, text}` | `{team, reply}` from the team's own Claude session, or `409` while it works a ticket. |

A box listens on port 8701 by default and accepts `POST /dispatch` and
`POST /message`.

## Configuration

- `serve --ttl` sets how many seconds a box can stay silent before the arbiter
  drops its teams. The default is 30.
- `serve --events-file` keeps unacked events across restarts.
- `box --heartbeat` sets how often a box re-registers. The default is 10.
- `box --advertise` sets the URL the arbiter uses to reach the box, for example
  its private IP in a VPC.
- `box --state-dir` sets where ticket payloads are written.
- `ARBITER_CLAUDE` overrides the command a box runs in place of `claude`.
- `ARBITER_URL` tells the arbiter plugin's MCP server where the service is.
  The default is `http://127.0.0.1:8700`.
- `box --warlock-cli` sets the path of Warlock's `scripts/warlock.py`, which
  turns on scope checks in `/worker:work`.

## Limits

- The registry lives in memory. If the service restarts, boxes re-register on
  their next heartbeat.
- There's no authentication. Run the service and boxes on a private network.
- Events reach the tracker only when the arbiter session runs `/arbiter:sync`.
  `/arbiter:watch` runs it on each new event, but only while the session is
  open.

## Test

```sh
python3 -m unittest discover -s tests
```

The tests use `tests/fake_claude.py` in place of the real CLI.
