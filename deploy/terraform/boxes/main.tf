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

# Claude on Bedrock, the GitHub App key, and Session Manager. Nothing else.
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
  name = "claude-and-github"
  role = aws_iam_role.worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
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
      },
      {
        Sid      = "GitHubAppKey"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = var.github_app_secret_arn
      },
    ]
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
    git_user_name         = var.git_user_name
    git_user_email        = var.git_user_email
    arbiter_repo          = var.arbiter_repo
    arbiter_ref           = var.arbiter_ref
    warlock_ref           = var.warlock_ref
    project_repo          = var.project_repo
    teams                 = each.value.teams
    arbiter_url           = local.arbiter.arbiter_url
    box_port              = local.arbiter.box_port
    aws_region            = local.arbiter.aws_region
    github_app_secret_arn = var.github_app_secret_arn
    claude_model          = var.claude_model
    allowed_tools         = concat(var.allowed_tools, each.value.allowed_tools)
  }
}
