# --- Required ---------------------------------------------------------------

variable "boxes" {
  description = <<-EOT
    Worker boxes, by name. Each lists the teams it serves, by tracker key: the
    prefix on the team's ticket numbers, as in .warlock/scopes.toml. A team
    belongs to one box.
  EOT
  type = map(object({
    teams               = list(string)
    instance_type       = optional(string, "t3.medium")
    architecture        = optional(string, "x86_64")
    root_volume_size_gb = optional(number, 40)
    allowed_tools       = optional(list(string), [])
  }))

  validation {
    condition     = length(flatten([for b in values(var.boxes) : b.teams])) == length(distinct(flatten([for b in values(var.boxes) : b.teams])))
    error_message = "A team can belong to only one box: two boxes would take the same tickets."
  }

  validation {
    condition     = alltrue([for b in values(var.boxes) : length(b.teams) > 0])
    error_message = "Every box needs at least one team."
  }
}

variable "project_repo" {
  description = "GitHub repository the teams work on, as OWNER/NAME. Use the same value as the arbiter state."
  type        = string
}

variable "git_user_name" {
  description = "Name on commits the boxes make, for example \"arbiter-bot\"."
  type        = string
}

variable "git_user_email" {
  description = "Email on commits the boxes make. For a GitHub App, use <app id>+<app slug>[bot]@users.noreply.github.com."
  type        = string
}

# --- Optional ---------------------------------------------------------------

variable "aws_profile" {
  description = "AWS CLI profile. Leave null to use the default credential chain. The region comes from the arbiter state."
  type        = string
  default     = null
}

variable "arbiter_state_path" {
  description = "Path to the arbiter state, which holds the arbiter's address and the security groups."
  type        = string
  default     = "../arbiter/terraform.tfstate"
}

variable "name" {
  description = "Name prefix for every AWS resource. Use the same value as the arbiter state."
  type        = string
  default     = "arbiter"
}

variable "claude_model" {
  description = "Bedrock model or inference profile ID for Claude Code. Null uses Claude Code's default for Bedrock."
  type        = string
  default     = null
}

variable "allowed_tools" {
  description = "Tools every box's Claude runs may use beyond the defaults (read, search, subagents, git, gh, python3), for example [\"Bash(npm:*)\"]. Add your build and test commands."
  type        = list(string)
  default     = []
}

variable "arbiter_repo" {
  type    = string
  default = "https://github.com/Genetic-Pottery/arbiter.git"
}

variable "arbiter_ref" {
  type    = string
  default = "main"
}

variable "warlock_ref" {
  type    = string
  default = "v0"
}
