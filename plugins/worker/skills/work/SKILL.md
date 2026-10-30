---
name: work
description: Work one ticket the arbiter handed over, from a payload file, and report every step as an event. Never touches the tracker.
disable-model-invocation: true
argument-hint: "<payload.json>"
---

Take one ticket to a pull request. The arbiter read the ticket from the tracker
and wrote it to the payload file in `$ARGUMENTS`. You have no tracker access:
everything the tracker would hear, you report as an event, and the arbiter
writes it to the ticket.

You are the orchestrator: you plan, dispatch each sub-task to a fresh subagent,
and commit. Keep your own context small, and leave reading and writing code to
the subagents.

Every run ends in exactly one outcome, reported as exactly one event:

- **done**: a pull request is open
- **paused**: something transient stopped the run, and the next dispatch
  resumes it
- **halted**: the ticket needs a person: a decision, an answer, or work outside
  the scope

A run that dies without a word is fine: the box reports that the run exited,
and the arbiter treats it as a pause.

## Events

Report with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/emit.py" <type> -`, with the
body on stdin, written `emit` below. Pass long bodies through a heredoc. The
body is the ticket comment the arbiter posts, so write it for a person.

| Type | When | Body |
|---|---|---|
| `plan` | After planning | The full plan comment, starting `Warlock plan` |
| `progress` | After each committed sub-task | The full plan comment, with that sub-task ticked |
| `done` | The pull request is open | The pull request URL on the first line, then a summary |
| `paused` | See "Pause" | Starts `Warlock paused:` |
| `halted` | See "Halt" | Starts `Warlock halted:` |

If `emit` fails, retry once. If it fails again, stop: without the arbiter,
nobody hears the outcome.

When the payload has `warlock_cli`, `warlock` below means
`python3 <warlock_cli>`. When it doesn't, skip every `warlock` step: the box
has no scope checks, and the CI check on the pull request is the only one.

## 1. Read the payload

Read the payload file. It holds `key`, `title`, `description`, `comments`
(oldest first), `target` (the branch the pull request merges into), and
sometimes `scope`, `url`, `test_plan`, and `warlock_cli`.

Check both. If one fails, emit `paused` with the reason and stop.

- `gh auth status` succeeds
- the working directory is a git repository

## 2. Start or resume

A comment whose body starts `Warlock plan` means an earlier run planned the
ticket: **resume**, using the newest one. Otherwise, **start**. Trackers can
change a comment's Markdown on the way back, for example `- [x]` to `* \[x\]`,
or add line breaks. Read the plan by its meaning: the branch, the target, and
which sub-tasks are ticked.

**Start:**

1. If `git status --porcelain` prints anything, emit `paused` and stop.
2. Run `git fetch origin`. If `origin/<target>` doesn't exist, run
   `git push origin origin/<default branch>:refs/heads/<target>`. If that push
   is rejected, another run created the branch first: run `git fetch origin`
   again.
3. If a local branch starting `<key in lowercase>-` exists, an earlier run
   halted before planning: switch to it. Otherwise run
   `git switch -c <key in lowercase>-<short slug> origin/<target>`.
4. Run `git config branch.<branch>.warlock-base <target>`.

**Resume:**

1. Run `git fetch origin`. Switch to the plan's branch: the local one if it
   exists, otherwise `git switch -c <branch> origin/<branch>`. If neither
   exists, the earlier run pushed nothing: start over from step 2 of **Start**
   with the plan's target and branch name.
2. Run `git config branch.<branch>.warlock-base <target>`, with the plan's
   target.
3. If `git status --porcelain` prints anything, it's the interrupted
   sub-task's partial work. Run
   `git stash push -u -m "worker: interrupted <KEY>"` and redo that sub-task.

## 3. Plan

Skip this step when resuming.

Read the ticket and its comments. A person's comment after a `Warlock halted:`
comment answers it, and binds the plan the way the description does. So does
each line of a `## Decisions` section in the description. Where an answer or a
decision contradicts the rest of the description, the answer or decision wins. Then read
only enough code to cut the work: names, file layout, where the tests live. Cut
the work into sub-tasks, in the order they're done. Each one:

- changes one coherent thing a subagent finishes in one sitting
- has a goal in one line, in the ticket's words
- has a definition of done: checkable statements, including the commands that
  show it holds
- lists likely files, and when `scope` is set, every one is inside it
  (`warlock where <file>...`)
- copies any rule the ticket fixes (a value, a name, what to leave alone) into
  the definition of done word for word

Between 1 and 8 sub-tasks. A ticket that's one small change is one sub-task.

Emit `plan` with the plan in this shape:

```markdown
Warlock plan
branch: <branch>
target: <target>

- [ ] 1. <goal>
  - done when: <statement>; <statement>
  - files: `<path>`, `<path>`
  - notes: <what the subagent needs that the ticket doesn't say>
- [ ] 2. ...
```

## 4. Work the sub-tasks

A sub-task is finished when `git log origin/<target>..HEAD --format=%s` lists a
commit starting `<KEY>.<N>:`. For each sub-task not finished, in order:

1. Dispatch a subagent with the Agent tool. Its prompt holds:
   - the line: "Read `${CLAUDE_PLUGIN_ROOT}/reference/subtask.md` and follow it."
   - the ticket key and title
   - this sub-task's entry from the plan
   - one line per finished sub-task saying what it changed
2. Read the report's first line.
   - **done:** run `warlock check`. If it prints `ok`, commit everything with
     the message `<KEY>.<N>: <goal>`, using the repository's git identity as
     configured. Run `git push -u origin HEAD`. Tick the sub-task in the plan
     and emit `progress` with the whole plan.
   - **failed:** dispatch one more fresh subagent with the same prompt plus the
     failure reason. If that one fails too, pause.
   - **blocked**, or `warlock check` lists a crossing: halt.

## 5. Finish

1. Run the ticket's test plan and `warlock check`. Done when both pass. If they
   fail, dispatch a subagent to fix what fails, and commit its work as
   `<KEY>.<N+1>: fix <what>`.
2. Run `gh label create warlock --description "Opened by Warlock" --force`, so
   the label exists. Open the pull request with
   `gh pr create --base <target> --label warlock`, titled
   `<KEY>: <ticket title>`. When `.github/pull_request_template.md` exists, fill
   every section from the sub-task reports.
3. Emit `done` with the pull request URL on the first line.

Reply with the pull request URL.

## 6. Pause

Pause when a sub-task fails twice, or when a `git` or `gh` step fails. These are
transient: a later run can succeed with no one changing anything.

1. If the ticket's newest two comments starting `Warlock` are both
   `Warlock paused:`, this would be the third pause in a row. Halt instead,
   giving the three reasons.
2. Run `git stash push -u -m "worker: paused <KEY>.<N>"` so the branch stays
   clean.
3. Emit `paused`. Start with `Warlock paused:` and the reason in one sentence,
   naming the sub-task. Then say which sub-tasks are committed, and that the
   next dispatch resumes it.

Reply with the reason.

## 7. Halt

Halt when the ticket needs a person: a sub-task is blocked or crosses the
scope, the ticket is ambiguous, or it has paused three times in a row.

1. Run `git stash push -u -m "worker: halted <KEY>.<N>"` so the branch stays
   clean.
2. Emit `halted`. Start with `Warlock halted:` and the reason in one sentence,
   naming the sub-task. Then say which sub-tasks are committed and what the
   ticket needs. When it needs an answer, end with the question on its own
   line, starting `Question:`.

Reply with the reason.
