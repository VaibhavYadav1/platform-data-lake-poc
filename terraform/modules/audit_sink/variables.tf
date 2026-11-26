variable "project_id" {
  description = "Sandbox project whose audit logs are collected."
  type        = string
}

variable "region" {
  description = "Location of the audit_logs dataset (D-21)."
  type        = string
  default     = "us-central1"
}

variable "dataset_id" {
  description = "Destination dataset (plan section 4.2)."
  type        = string
  default     = "audit_logs"
}

variable "sink_name" {
  description = "Log sink name (plan D8)."
  type        = string
  default     = "poc-bq-audit"
}

variable "enable_iamcredentials_data_access_logs" {
  description = "Turn on data access logs for iamcredentials.googleapis.com, so impersonation attempts are logged (design issue #3)."
  type        = bool
  default     = true
}
