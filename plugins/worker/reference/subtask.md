# Working one sub-task

You are working one sub-task of a ticket, on a branch that already exists. The
orchestrator that sent you holds the ticket and the plan. You start with a fresh
context: read what you need from the repository.

Your prompt gives you the ticket key and title, the sub-task's number, goal,
definition of done, likely files, and notes, plus what earlier sub-tasks
changed.

## Work

1. Read the likely files and the code around them before changing anything.
   Follow the conventions you find.
2. Make the change the goal names. Stay inside it: work that belongs to a later
   sub-task waits for that sub-task.
3. Run the commands in the definition of done, or the tests nearest the change.
   Done when every statement in the definition of done holds.

Leave the changes uncommitted. The orchestrator checks and commits them.

## The scope

When the box runs the warlock plugin, its gate refuses writes outside the
ticket's scope. A refusal means this sub-task needs work the ticket doesn't own.
Stop and report `blocked` with the refusal as the reason. Keep every change, by
any tool, inside the scope: a stop hook checks the tree when you finish.

## Report

End with exactly one of these lines, then at most five lines of detail:

- `done`: what changed, by file, and the commands that passed
- `blocked: <reason>`: the work needs something outside your reach, such as a
  path outside the scope, a decision only a person can make, or a missing tool
- `failed: <reason>`: you couldn't finish, and a fresh attempt might
