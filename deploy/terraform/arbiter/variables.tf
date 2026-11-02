# --- Required ---------------------------------------------------------------

variable "git_user_name" {
  description = "Name for git commits made on the arbiter box."
  type        = string
}

variable "git_user_email" {
  description = "Email for git commits made on the arbiter box."
  type        = string
}

variable "tailscale_auth_key" {
  description = "One-time Tailscale auth key. You log in to the arbiter box over Tailscale SSH to finish its setup."
  type        = string
  sensitive   = true

  validation {
    condition     = startswith(var.tailscale_auth_key, "tskey-auth-")
    error_message = "Use a Tailscale auth key, which starts with tskey-auth-."
  }
}

variable "repos" {
  description = "GitHub repositories the teams work in, as OWNER/NAME. Each must have .warlock/scopes.toml, and the GitHub App must be installed on each. One installation covers one owner, so they all share it."
  type        = list(string)

  validation {
    condition     = length(var.repos) > 0 && alltrue([for r in var.repos : length(split("/", r)) == 2])
    error_message = "repos must list at least one OWNER/NAME, for example [\"Genetic-Pottery/app\"]."
  }

  validation {
    condition     = length(distinct([for r in var.repos : split("/", r)[0]])) <= 1
    error_message = "Every repository must have the same owner: the GitHub App's installation covers one."
  }

  validation {
    condition     = length(distinct([for r in var.repos : split("/", r)[1]])) == length(var.repos)
    error_message = "Each repository needs its own name: the arbiter box clones them side by side."
  }
}

variable "github_app_secret_arn" {
  description = "Secrets Manager secret holding the GitHub App as JSON: app_id, installation_id, and private_key (the PEM text). Only the arbiter box can read it."
  type        = string
}

# --- Optional ---------------------------------------------------------------

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "aws_profile" {
  description = "AWS CLI profile. Leave null to use the default credential chain."
  type        = string
  default     = null
}

variable "name" {
  description = "Name prefix for every AWS resource."
  type        = string
  default     = "arbiter"
}

variable "instance_type" {
  description = "The arbiter box runs the service and one or two Claude sessions."
  type        = string
  default     = "t3.medium"
}

variable "architecture" {
  type    = string
  default = "x86_64"
}

variable "arbiter_repo" {
  description = "Git URL of the arbiter repository. The arbiter service clones it on boot, before anyone logs in, so it must be readable without credentials."
  type        = string
  default     = "https://github.com/Genetic-Pottery/arbiter.git"
}

variable "arbiter_ref" {
  description = "Branch or tag of arbiter to run."
  type        = string
  default     = "main"
}

variable "warlock_ref" {
  description = "Branch or tag of the warlock plugin to install."
  type        = string
  default     = "v0"
}

variable "arbiter_port" {
  type    = number
  default = 8700
}

variable "box_port" {
  type    = number
  default = 8701
}
