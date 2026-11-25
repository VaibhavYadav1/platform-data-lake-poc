variable "project_id" {
  description = "Sandbox project that runs the workflows."
  type        = string
}

variable "region" {
  description = "Region of the workflows, scheduler jobs, Cloud SQL and Datastream."
  type        = string
  default     = "us-central1"
}

variable "orchestrator_service_account_email" {
  description = "Email of sa-orchestrator. Runs the workflows and the scheduler jobs that start them."
  type        = string
}

variable "schedule_time_zone" {
  description = "Team's time zone for the night-off and morning-on schedules (IANA name)."
  type        = string
  default     = "Asia/Kolkata"
}

# ---- E8: night-off and morning-on -----------------------------------------------------------

variable "night_off_schedule" {
  description = "Cron for poc-night-off: 20:00, Monday to Friday."
  type        = string
  default     = "0 20 * * 1-5"
}

variable "morning_on_schedule" {
  description = "Cron for poc-morning-on: 08:00, Monday to Friday."
  type        = string
  default     = "0 8 * * 1-5"
}

variable "schedule_paused" {
  description = "Create the night-off and morning-on scheduler jobs paused. Run each workflow by hand once, then set this to false."
  type        = bool
  default     = true
}

variable "sql_instance_name" {
  description = "Cloud SQL instance that night-off stops and morning-on starts."
  type        = string
  default     = "poc-ops-db"
}

variable "datastream_stream_id" {
  description = "Datastream stream that night-off pauses and morning-on resumes."
  type        = string
  default     = "poc-cdc-stream"
}

variable "simulator_scheduler_jobs" {
  description = "Scheduler job ids of the simulator. Paused at night, resumed first in the morning."
  type        = list(string)
  default     = ["poc-simulator-tick"] # A8's scheduler job (guide 5.3); was "poc-simulator", which doesn't exist
}

variable "delayed_scheduler_jobs" {
  description = "Scheduler job ids of micro-batch (dev and int) and the watchdog. Paused at night, resumed last in the morning."
  type        = list(string)
  default     = ["poc-micro-batch-dev", "poc-micro-batch-int", "poc-watchdog"]
}

variable "morning_delay_seconds" {
  description = "Wait between resuming the simulator and resuming micro-batch and watchdog, so the first freshness check sees new data."
  type        = number
  default     = 300
}

variable "manage_orchestrator_iam" {
  description = "Grant sa-orchestrator the rights night-off and morning-on need. Set to false if the service_accounts module (D2) already grants them."
  type        = bool
  default     = true
}

# ---- E7: watchdog ---------------------------------------------------------------------------

variable "watchdog_interval_minutes" {
  description = "How often poc-watchdog runs. Interval 5 plus a threshold of 8 minutes keeps detection inside the 15-minute promise."
  type        = number
  default     = 5
}

# ---- E6: full load --------------------------------------------------------------------------

variable "full_load_environments" {
  description = "Environments that get a full-load workflow and scheduler. Add int in E9, once poc-dbt-runner-int exists."
  type        = set(string)
  default     = ["dev"]
}

variable "full_load_schedule" {
  description = "Cron for poc-full-load: 20:15, Monday to Friday."
  type        = string
  default     = "15 20 * * 1-5"
}
