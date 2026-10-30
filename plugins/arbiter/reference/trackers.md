# Tracker operations

Warlock reaches trackers only through their official MCP servers. Tool names
change between server versions, so if a name below is missing, pick the tool
whose description matches.

The Atlassian server exposes a few Jira tools directly and the rest as
operations: find an operation with `discover`, then run it with `executeRead` or
`executeWrite`. Every Jira call needs the site's cloud id, which
`getAccessibleAtlassianResources` returns.

Every operation uses the scope's `team` and `label` from `.warlock/scopes.toml`.
If the server for a scope's `tracker` isn't connected, stop and tell the person
to add it:

- Linear: `claude mcp add --transport http linear https://mcp.linear.app/mcp`
- Jira: connect the Atlassian MCP server (Atlassian Rovo).

## Words

| Warlock | Linear | Jira |
|---|---|---|
| team | team key | project key |
| brief | project | epic |
| ticket | issue | issue (story or task) |
| unstarted | a state of type `unstarted`, such as Todo or Backlog | status category To Do |
| started | a state of type `started`, such as In Progress | status category In Progress |
| blocked by | relation `blocked by` (`save_issue` `blockedBy`) | link type `Blocks` (operation `createJiraIssueLink`, the blocker as `inwardIssue`) |

## Push a brief

- **Linear:** create a project (`save_project`) on the team, named after the
  brief's title, with the brief as its description and the label as a project
  label. If the project label doesn't exist, create it first
  (`save_project_label`).
- **Jira:** create an issue of type Epic (`createJiraIssue`) in the project, with
  the brief's title as the summary, the brief as the description, and the label.
  Send the description as Markdown and let the server convert it.

## List briefs to draft

Projects (Linear `list_projects`) or epics (Jira `searchJiraIssuesUsingJql`) in the team that carry the
label and have no child tickets yet.

## File a ticket

Create an issue (Linear `save_issue`) in the slice's team with:

- the title, and the description filled from the ticket template
- the parent: the project (Linear) or epic (Jira)
- the label. If the issue label doesn't exist, create it first (Linear
  `save_issue_label`).
- the assignee: the signed-in user (Linear `me`; Jira: look up the current user)
- an unstarted state

Create `blocked by` relations after every ticket of the brief exists, so each
link points at a real key. If Jira refuses an epic parent across projects, file
the ticket without a parent, link it to the epic with `relates to`, and say so.

## The queue

Tickets in the team (Linear `list_issues`, Jira `searchJiraIssuesUsingJql`) that:

- are assigned to the signed-in user
- carry the label
- are in an unstarted state
- have no `blocked by` ticket that is unfinished (Linear: state type
  `completed` or `canceled` counts as finished; Jira: status category Done)

Order by priority, then by oldest first.

## Move a ticket

- **Linear:** set the state by name (`save_issue` with the issue's id). List
  the team's states first (`list_issue_statuses`) if the name might differ.
- **Jira:** list the issue's transitions (operation `listJiraIssueTransitions`) and run
  the one whose target status has the name you want (`transitionJiraIssue`). If
  no transition reaches it, comment with the reason instead of guessing.

## Move a project

- **Linear:** set the project's status by name (`save_project` with the
  project's id).
- **Jira:** run the epic's transition to the status, as for a ticket.

If no status or transition has that name, leave the project where it is and say
so in your reply, naming the setting (`project_start_state` or
`project_review_state`) so the person can change it.

## Comment

`save_comment` (Linear) or `addOrEditJiraIssueComment` (Jira), in Markdown.
