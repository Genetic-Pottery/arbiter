# Deploy arbiter on AWS

This directory runs arbiter on EC2: one arbiter box, the front door you talk to
from the Claude app, and any number of worker boxes that work tickets. Every
box runs NixOS and builds itself from `nixos/` on first boot.

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
                            worker boxes :8701 ── GitHub (GitHub App)
                            Claude on Bedrock (IAM role)
```

## What each box gets

The arbiter box:

- the arbiter service, which restarts on its own
- Claude Code with Remote Control, started in your project's checkout
- the warlock and arbiter plugins, installed by `arbiter-install`
- Tailscale SSH for you, and no open ports except the arbiter service, which
  only worker boxes can reach

Each worker box:

- the box agent, serving the teams you list for it, with one clone of your
  project per team
- Claude Code on Bedrock, through the box's IAM role, so no Claude login
- a GitHub App installation token, minted from Secrets Manager and refreshed
  every 40 minutes, so no GitHub login
- no person logs in. To look around, use Session Manager:
  `aws ssm start-session --target <instance id>`

## Before you start

You need the following:

- Terraform 1.6 or later, and AWS credentials the AWS CLI can use.
- The arbiter repository readable without credentials at `arbiter_repo`. The
  arbiter service clones it on boot, before anyone logs in.
- A project repository set up with `/warlock:init`, so it has
  `.warlock/scopes.toml`.
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
4. Install the app on your project repository. Note the installation ID, the
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
   and fill it in.
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

1. Copy `terraform/boxes/terraform.tfvars.example` to `terraform.tfvars`. Name
   each team by its tracker key, as in `.warlock/scopes.toml`. A team belongs
   to one box.
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

## Limits

- The arbiter service has no authentication. The security groups are its only
  protection: keep the boxes in their own VPC or account if anything else runs
  there.
- Replacing the arbiter box changes its private address. Apply
  `terraform/boxes` again afterward, which replaces the workers.
- First-boot files go in EC2 user data, which is capped at 16 KB. The NixOS
  configuration uses about 13 KB of it.
- Boxes follow `arbiter_ref` and `warlock_ref` only when they're created.
  To update a box, replace it.
