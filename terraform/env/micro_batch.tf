# E4: the micro-batch workflow and its scheduler, once per environment.
#
# Prerequisites that other tasks own: sa-orchestrator (D2), poc-dbt-runner-<env> (E3),
# poc-crm-loader (B3). Until they exist the workflow deploys but cannot run, and the scheduler job
# stays paused.

variable "orchestrator_service_account_email" {
  description = "sa-orchestrator. Created by the service_accounts module (D2); until then, by hand."
  type        = string
  default     = "sa-orchestrator@gks-datalake-poc2-dev.iam.gserviceaccount.com"
}

variable "micro_batch_schedule" {
  description = "Cron for the micro-batch scheduler job: every 15 minutes in dev, hourly in int."
  type        = string
  default     = "0 * * * *"
}

variable "run_crm_loader" {
  description = "Run poc-crm-loader at the start of every micro-batch. True in dev, false in int."
  type        = bool
  default     = false
}

variable "micro_batch_schedule_paused" {
  description = "Keep the micro-batch scheduler job paused. Set to false after the workflow has been run by hand once."
  type        = bool
  default     = true
}

module "micro_batch" {
  source = "../modules/micro_batch"

  project_id                         = var.project_id
  region                             = var.region
  env                                = var.env
  orchestrator_service_account_email = var.orchestrator_service_account_email
  schedule                           = var.micro_batch_schedule
  run_crm_loader                     = var.run_crm_loader
  schedule_paused                    = var.micro_batch_schedule_paused
}
