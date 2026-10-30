# The boxes state reads these.

output "arbiter_url" {
  description = "Where boxes reach the arbiter service, on the private network."
  value       = "http://${module.box.private_ip}:${var.arbiter_port}"
}

output "worker_security_group_id" {
  value = aws_security_group.worker.id
}

output "subnet_id" {
  value = data.aws_subnets.default.ids[0]
}

output "box_port" {
  value = var.box_port
}

output "aws_region" {
  value = var.aws_region
}

output "instance_id" {
  value = module.box.instance_id
}

output "next_steps" {
  value = <<-EOT
    1. Wait for ${var.name}-arbiter to appear in your Tailscale admin console.
    2. SSH to ${var.name}-arbiter as arbiter. No password or key.
    3. Log in to GitHub:   gh auth login
    4. Log in to Claude:   claude   (then /mcp to sign in to Linear or Jira)
    5. Install plugins:    arbiter-install
    6. Remote Control:     remote-control-enable
    7. In the Claude app, open a session and run /arbiter:watch.
    Then apply deploy/terraform/boxes.
  EOT
}
