# E8: night-off and morning-on. One of each for the whole sandbox, so they live in shared,
# not in env (env is applied once per environment and would create them twice).
#
# Prerequisites that other tasks own: sa-orchestrator (D2), Cloud SQL poc-ops-db (A1),
# Datastream poc-cdc-stream (A4). Until they exist the workflows deploy but cannot run, and the
# scheduler jobs stay paused.

variable "orchestrator_service_account_email" {
  description = "sa-orchestrator. Created by the service_accounts module (D2); until then, by hand."
  type        = string
  default     = "sa-orchestrator@gks-datalake-poc2-dev.iam.gserviceaccount.com"
}

variable "schedule_time_zone" {
  description = "Team's time zone for the night-off and morning-on schedules (IANA name)."
  type        = string
  default     = "Asia/Kolkata"
}

variable "night_off_schedule_paused" {
  description = "Keep the night-off and morning-on scheduler jobs paused. Set to false after each workflow has been run by hand once."
  type        = bool
  default     = true
}

module "night_off" {
  source = "../modules/workflows"

  project_id                         = var.project_id
  region                             = var.region
  orchestrator_service_account_email = var.orchestrator_service_account_email
  schedule_time_zone                 = var.schedule_time_zone
  schedule_paused                    = var.night_off_schedule_paused
}
