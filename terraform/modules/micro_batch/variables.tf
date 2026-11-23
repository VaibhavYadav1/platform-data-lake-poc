variable "project_id" {
  description = "GCP project of this environment."
  type        = string
}

variable "region" {
  description = "Region of the workflow and the scheduler job."
  type        = string
  default     = "us-central1"
}

variable "env" {
  description = "Environment name: dev or int. Part of the workflow and scheduler job names."
  type        = string
}

variable "orchestrator_service_account_email" {
  description = "Email of sa-orchestrator. Runs the workflow and the scheduler job that starts it."
  type        = string
}

variable "schedule" {
  description = "Cron for the micro-batch: every 15 minutes in dev, hourly in int."
  type        = string
  default     = "0 * * * *"
}

variable "run_crm_loader" {
  description = "Run poc-crm-loader at the start of every cycle. True in dev, false in int."
  type        = bool
  default     = false
}

variable "schedule_paused" {
  description = "Create the scheduler job paused. Run the workflow by hand once, then set this to false. Terraform ignores later changes: night-off and morning-on pause and resume the job."
  type        = bool
  default     = true
}
