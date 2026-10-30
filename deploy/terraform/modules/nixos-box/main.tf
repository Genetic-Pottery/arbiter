# One NixOS EC2 instance that builds itself from deploy/nixos on first boot.

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

variable "name" {
  description = "Instance name and hostname."
  type        = string
}

variable "role" {
  description = "NixOS configuration to build: \"arbiter\" or \"worker\"."
  type        = string

  validation {
    condition     = contains(["arbiter", "worker"], var.role)
    error_message = "role must be \"arbiter\" or \"worker\"."
  }
}

variable "box" {
  description = "Values the NixOS configuration reads from /etc/nixos/box.json, beyond the ones this module sets."
  type        = any
}

variable "instance_type" {
  type = string
}

variable "architecture" {
  description = "\"x86_64\" or \"arm64\". Must match instance_type."
  type        = string
  default     = "x86_64"
}

variable "nixos_release" {
  description = "NixOS release of the base image. Also system.stateVersion; don't change it on a running box."
  type        = string
  default     = "26.05"
}

variable "username" {
  type    = string
  default = "arbiter"
}

variable "subnet_id" {
  type = string
}

variable "security_group_ids" {
  type = list(string)
}

variable "iam_instance_profile" {
  type = string
}

variable "root_volume_size_gb" {
  type    = number
  default = 40
}

variable "tailscale_auth_key" {
  description = "Joins the box to your tailnet on first boot. Empty for boxes nobody logs in to."
  type        = string
  default     = ""
  sensitive   = true
}

# Official NixOS images, published weekly by the NixOS project.
# See https://nixos.github.io/amis/
data "aws_ami" "nixos" {
  most_recent = true
  owners      = ["427812963091"]

  filter {
    name   = "name"
    values = ["nixos/${var.nixos_release}*"]
  }

  filter {
    name   = "architecture"
    values = [var.architecture]
  }
}

locals {
  nixos_dir = "${path.module}/../../../nixos"

  box_json = jsonencode(merge(var.box, {
    username      = var.username
    hostname      = var.name
    state_version = var.nixos_release
    host_platform = var.architecture == "arm64" ? "aarch64-linux" : "x86_64-linux"
  }))

  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    role = var.role
    nix_files = {
      for f in ["flake.nix", "common.nix", "${var.role}.nix"] :
      f => base64encode(file("${local.nixos_dir}/${f}"))
    }
    box_json          = base64encode(local.box_json)
    tailscale_authkey = var.tailscale_auth_key == "" ? "" : base64encode(var.tailscale_auth_key)
  })
}

resource "aws_instance" "this" {
  ami                    = data.aws_ami.nixos.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = var.security_group_ids
  iam_instance_profile   = var.iam_instance_profile

  # A public IP for outbound traffic only. It avoids paying for a NAT gateway.
  associate_public_ip_address = true

  user_data                   = local.user_data
  user_data_replace_on_change = true

  root_block_device {
    volume_size = var.root_volume_size_gb
    volume_type = "gp3"
    encrypted   = true
  }

  metadata_options {
    http_tokens = "required"
  }

  tags = {
    Name = var.name
    Role = var.role
  }

  lifecycle {
    # A newer NixOS image must not silently rebuild the box.
    ignore_changes = [ami]
  }
}

output "instance_id" {
  value = aws_instance.this.id
}

output "private_ip" {
  value = aws_instance.this.private_ip
}
