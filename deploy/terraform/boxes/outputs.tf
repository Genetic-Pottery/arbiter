output "boxes" {
  description = "Each box's instance ID, private address, and teams."
  value = {
    for name, b in module.box : name => {
      instance_id = b.instance_id
      private_ip  = b.private_ip
      teams       = var.boxes[name].teams
    }
  }
}

output "connect" {
  description = "To open a shell on a box, run one of these."
  value       = { for name, b in module.box : name => "aws ssm start-session --target ${b.instance_id}" }
}
