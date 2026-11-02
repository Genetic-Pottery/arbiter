# Deploy arbiter on AWS

This directory runs arbiter on EC2: one arbiter box, the front door you talk to
from the Claude app, and any number of worker boxes that work tickets. The
teams can work in any number of repositories that one GitHub owner holds.
Every box runs NixOS and builds itself from `nixos/` on first boot.

The arbiter and the workers live in two Terraform states:

- `terraform/arbiter` creates the arbiter box and the security groups. You
  apply it once.
- `terraform/boxes` creates the workers from a `boxes` map. You change it
  whenever you add, remove, or move teams. Applying it never touches the
  arbiter.

```
you (Claude app) ── Remote Control ──> arbiter box ── Linear / Jira
                                          │  arbiter service :8700
                       security groups    │
                                          v
                            worker boxes :8701 ── GitHub (tokens from the arbiter)
                            Claude on Bedrock (IAM role)
```

## What each box gets

The arbiter box:

- the arbiter service, which restarts on its own
- Claude Code with Remote Control, started in `~/Projects`, which holds a
  checkout of each repository
- the warlock and arbiter plugins, installed by `arbiter-install`
- Tailscale SSH for you, and no open ports except the arbiter service, which
  only worker boxes can reach
- read access to the GitHub App's key in Secrets Manager. The arbiter service
  copies the key into memory at start and issues worker boxes their tokens.

Each worker box:

- the box agent, serving the teams you list for it, with one clone of its
  repository per team
- Claude Code on Bedrock, through the box's IAM role, so no Claude login
- an hour-long GitHub token from the arbiter, scoped to its teams'
  repositories and refreshed every 40 minutes, so no GitHub login and no key.
  The box can't read the secret.
- no person logs in. To look around, use Session Manager:
  `aws ssm start-session --target <instance id>`

## Before you start

You need the following:

- Terraform 1.6 or later, and AWS credentials the AWS CLI can use.
- The arbiter repository readable without credentials at `arbiter_repo`. The
  arbiter service clones it on boot, before anyone logs in.
- One or more project repositories with the same owner, each set up with
  `/warlock:init`, so it has `.warlock/scopes.toml`. A team key must appear in
  only one of them.
- A Claude Pro, Max, Team, or Enterprise plan for the arbiter box's login.
  Remote Control needs it.
- A Tailscale account, for logging in to the arbiter box.
- Bedrock access to Claude models in your region. In the Bedrock console,
  open **Model access** and request the Anthropic models.

### Create the GitHub App

Workers push branches and open pull requests as a GitHub App.

1. In your GitHub organization's settings, open **Developer settings > GitHub
   Apps** and click **New GitHub App**.
2. Turn off **Webhook**. Grant these repository permissions:
   - **Contents:** read and write
   - **Pull requests:** read and write
   - **Metadata:** read-only
3. Create the app, note its **App ID**, and generate a private key.
4. Install the app on each project repository. Note the installation ID, the
   number at the end of the installation's URL.
5. Store all three in Secrets Manager:

   ```sh
   aws secretsmanager create-secret --name arbiter-github-app \
     --secret-string "$(jq -n --arg id APP_ID --arg inst INSTALLATION_ID \
       --rawfile key path/to/private-key.pem \
       '{app_id: $id, installation_id: $inst, private_key: $key}')"
   ```

   Note the secret's ARN from the output.

## Create the arbiter box

1. In the Tailscale admin console, generate an auth key.
2. Copy `terraform/arbiter/terraform.tfvars.example` to `terraform.tfvars`
   and fill it in. List every project repository in `repos`, and set the
   secret's ARN as `github_app_secret_arn`.
3. Apply:

   ```sh
   cd terraform/arbiter
   terraform init
   terraform apply
   ```

4. Follow `next_steps` in the output. In short: SSH in over Tailscale, run
   `gh auth login` and `claude`, sign in to your tracker with `/mcp`, then run
   `arbiter-install` and `remote-control-enable`.
5. In the Claude app, open a session on the arbiter box and run
   `/arbiter:watch`.

## Add worker boxes

1. Copy `terraform/boxes/terraform.tfvars.example` to `terraform.tfvars`. In
   `teams`, map each team's tracker key, as in `.warlock/scopes.toml`, to the
   repository it works in. In `boxes`, list each box's teams. A team belongs to
   one box, and one box can serve teams from different repositories.
2. Apply:

   ```sh
   cd terraform/boxes
   terraform init
   terraform apply
   ```

A new box takes about ten minutes to build NixOS and start. Within one heartbeat
after that, its teams show up in the arbiter's `list_teams`.

To change the fleet, edit `boxes` and apply again:

- **Add a box:** Terraform creates only that box.
- **Remove a box:** Terraform destroys it. If it was working a ticket,
  `/arbiter:sync` finds the lost run and pauses the ticket. The next dispatch
  to a box that serves the team resumes it.
- **Move a team:** Terraform replaces the boxes whose teams changed, because
  their teams are part of the first-boot configuration.
- **Add a repository:** install the GitHub App on it, add it to `repos` in
  the arbiter state, and apply that state. This replaces the arbiter box, so
  follow `next_steps` again. Then add its teams to the boxes state and apply.

### Use the Claude API instead of Bedrock

Workers run Claude on Bedrock by default. To use an Anthropic API key instead,
for example while a new AWS account waits for Bedrock access, do the following:

1. In the Claude Console, create an API key.
2. Store it in Secrets Manager as plain text:

   ```sh
   read -rsp 'API key: ' K && printf %s "$K" | aws secretsmanager create-secret \
     --region us-east-1 --name arbiter-anthropic-api-key \
     --secret-string file:///dev/stdin --query ARN --output text; unset K
   ```

3. In `terraform/boxes/terraform.tfvars`, set `anthropic_api_key_secret_arn`
   to the secret's ARN, and set `claude_model` to a Claude API model ID such as
   `claude-sonnet-5-5`.

Each worker box reads the key when its agent starts. Only worker boxes can read
the secret. To rotate the key, store the new one with
`aws secretsmanager put-secret-value` and restart the `arbiter-box` service.

## Limits

- The arbiter service has no authentication. The security groups are its only
  protection: keep the boxes in their own VPC or account if anything else runs
  there.
- Replacing the arbiter box changes its private address. Apply
  `terraform/boxes` again afterward, which replaces the workers.
- First-boot files go in EC2 user data, which is capped at 16 KB. The NixOS
  configuration uses about 14 KB of it.
- The arbiter box's repositories are part of its first-boot configuration, so
  changing `repos` replaces it, and you log in on it again.
- Boxes follow `arbiter_ref` and `warlock_ref` only when they're created.
  To update a box, replace it.
- Workers depend on the arbiter for GitHub access. If the arbiter is down for
  more than an hour, their tokens expire and their runs fail to push.
- The arbiter gives a token to any address registered as a box, and any
  machine in the worker security group can register. Keep that group to
  worker boxes.
