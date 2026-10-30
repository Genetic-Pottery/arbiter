# The front door: the arbiter box, and the security groups every box uses.
# Keep this in its own state, so changing the boxes never touches it.

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
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project   = "arbiter"
      ManagedBy = "terraform"
    }
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

# The arbiter service has no authentication, so these two groups are the only
# thing between it and the network: boxes reach the arbiter, the arbiter
# reaches boxes, and nothing else gets in.
resource "aws_security_group" "arbiter" {
  name        = "${var.name}-arbiter"
  description = "Arbiter service, reachable from worker boxes only."
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_security_group" "worker" {
  name        = "${var.name}-worker"
  description = "Box agents, reachable from the arbiter only."
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "arbiter_from_workers" {
  security_group_id            = aws_security_group.arbiter.id
  referenced_security_group_id = aws_security_group.worker.id
  ip_protocol                  = "tcp"
  from_port                    = var.arbiter_port
  to_port                      = var.arbiter_port
  description                  = "Heartbeats and events from boxes"
}

resource "aws_vpc_security_group_ingress_rule" "workers_from_arbiter" {
  security_group_id            = aws_security_group.worker.id
  referenced_security_group_id = aws_security_group.arbiter.id
  ip_protocol                  = "tcp"
  from_port                    = var.box_port
  to_port                      = var.box_port
  description                  = "Dispatches from the arbiter"
}

resource "aws_vpc_security_group_egress_rule" "all" {
  for_each = {
    arbiter = aws_security_group.arbiter.id
    worker  = aws_security_group.worker.id
  }
  security_group_id = each.value
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
  description       = "All outbound"
}

# Session Manager only. The arbiter box reaches Claude and the trackers with
# your claude.ai login, not AWS.
resource "aws_iam_role" "arbiter" {
  name = "${var.name}-arbiter"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "arbiter_ssm" {
  role       = aws_iam_role.arbiter.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "arbiter" {
  name = "${var.name}-arbiter"
  role = aws_iam_role.arbiter.name
}

module "box" {
  source = "../modules/nixos-box"

  name                 = "${var.name}-arbiter"
  role                 = "arbiter"
  instance_type        = var.instance_type
  architecture         = var.architecture
  subnet_id            = data.aws_subnets.default.ids[0]
  security_group_ids   = [aws_security_group.arbiter.id]
  iam_instance_profile = aws_iam_instance_profile.arbiter.name
  tailscale_auth_key   = var.tailscale_auth_key

  box = {
    git_user_name  = var.git_user_name
    git_user_email = var.git_user_email
    arbiter_repo   = var.arbiter_repo
    arbiter_ref    = var.arbiter_ref
    warlock_ref    = var.warlock_ref
    project_repo   = var.project_repo
    project_name   = element(split("/", var.project_repo), 1)
    arbiter_port   = var.arbiter_port
  }
}
