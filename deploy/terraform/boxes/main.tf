# Worker boxes. Add, remove, or change an entry in `boxes` and apply: Terraform
# touches only that box, and the arbiter learns about it from its heartbeat.

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region  = local.arbiter.aws_region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project   = "arbiter"
      ManagedBy = "terraform"
    }
  }
}

data "terraform_remote_state" "arbiter" {
  backend = "local"
  config = {
    path = var.arbiter_state_path
  }
}

data "aws_caller_identity" "current" {}

locals {
  arbiter = data.terraform_remote_state.arbiter.outputs
}

# Checks the teams before any box is built from them.
resource "terraform_data" "teams" {
  lifecycle {
    precondition {
      condition     = alltrue([for b in values(var.boxes) : alltrue([for t in b.teams : contains(keys(var.teams), t)])])
      error_message = "Every team a box lists needs an entry in `teams` with its repository."
    }
    precondition {
      # An arbiter state from before `repos` existed has no such output.
      condition     = try(local.arbiter.repos, null) == null || alltrue([for repo in values(var.teams) : contains(local.arbiter.repos, repo)])
      error_message = "Every repository in `teams` must be in the arbiter state's `repos`, or the arbiter refuses the box a token for it."
    }
  }
}

# Claude on Bedrock and Session Manager. Nothing else: GitHub access comes as
# hour-long tokens from the arbiter service, never the App's key.
resource "aws_iam_role" "worker" {
  name = "${var.name}-worker"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "worker" {
  name = "claude-on-bedrock"
  role = aws_iam_role.worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ClaudeOnBedrock"
      Effect = "Allow"
      Action = [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:ListInferenceProfiles",
        "bedrock:GetInferenceProfile",
      ]
      Resource = [
        "arn:aws:bedrock:*::foundation-model/anthropic.*",
        "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/*",
      ]
    }]
  })
}

# With an API key in place of Bedrock, the box reads that one secret at start.
resource "aws_iam_role_policy" "worker_api_key" {
  count = var.anthropic_api_key_secret_arn == null ? 0 : 1
  name  = "anthropic-api-key"
  role  = aws_iam_role.worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = var.anthropic_api_key_secret_arn
    }]
  })
}

resource "aws_iam_role_policy_attachment" "worker_ssm" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "worker" {
  name = "${var.name}-worker"
  role = aws_iam_role.worker.name
}

module "box" {
  source   = "../modules/nixos-box"
  for_each = var.boxes

  name                 = "${var.name}-${each.key}"
  role                 = "worker"
  instance_type        = each.value.instance_type
  architecture         = each.value.architecture
  root_volume_size_gb  = each.value.root_volume_size_gb
  subnet_id            = local.arbiter.subnet_id
  security_group_ids   = [local.arbiter.worker_security_group_id]
  iam_instance_profile = aws_iam_instance_profile.worker.name

  box = {
    git_user_name  = var.git_user_name
    git_user_email = var.git_user_email
    arbiter_repo   = var.arbiter_repo
    arbiter_ref    = var.arbiter_ref
    warlock_ref    = var.warlock_ref
    teams          = { for team in each.value.teams : team => lookup(var.teams, team, null) }
    arbiter_url    = local.arbiter.arbiter_url
    box_port       = local.arbiter.box_port
    aws_region     = local.arbiter.aws_region
    claude_model   = var.claude_model
    allowed_tools  = concat(var.allowed_tools, each.value.allowed_tools)

    anthropic_api_key_secret_arn = var.anthropic_api_key_secret_arn
  }

  # The policy must exist before the box asks for the key.
  depends_on = [aws_iam_role_policy.worker_api_key, terraform_data.teams]
}
