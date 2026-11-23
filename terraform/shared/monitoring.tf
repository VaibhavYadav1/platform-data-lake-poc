# E7: the team's email channel, the log-based metrics and the four alert policies.
# One set for the sandbox: the workflows and the logs they alert on are in this one project.

variable "alert_email" {
  description = "Team address for every alert. Set it in terraform.tfvars. Empty: the policies exist but notify nobody, and Terraform warns."
  type        = string
  default     = ""
}

module "monitoring" {
  source = "../modules/monitoring"

  project_id  = var.project_id
  alert_email = var.alert_email
}
