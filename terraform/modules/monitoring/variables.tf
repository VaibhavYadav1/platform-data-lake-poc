variable "project_id" {
  description = "GCP project that holds the workflows and the logs."
  type        = string
}

variable "alert_email" {
  description = "Team address that receives every alert. Empty creates the policies with no notification, and Terraform warns."
  type        = string
}

variable "workflow_name_pattern" {
  description = "RE2 regular expression for the workflows the failure alert watches (full match)."
  type        = string
  default     = "poc-.*"
}
