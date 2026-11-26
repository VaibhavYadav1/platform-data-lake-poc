# E3: Cloud Run job poc-dbt-runner-{env}.
# B3: Cloud Run job poc-crm-loader (shared, one per sandbox).
#
# Both jobs are created on first apply and updated on every merge when Cloud
# Build passes the new commit SHA as TF_VAR_image_tag.

variable "dbt_runner_service_account_email" {
  description = "Email of sa-dwh-writer-{env}. Created by the service_accounts module (D2); until then, set by hand."
  type        = string
  default     = "sa-dwh-writer-dev@gks-datalake-poc2-dev.iam.gserviceaccount.com"
}

variable "image_tag" {
  description = "Docker image tag for the dbt-runner image. Set to the commit SHA by Cloud Build (TF_VAR_image_tag). Use 'latest' before the first merge builds the image."
  type        = string
  default     = "latest"
}

# ---- B3: CRM loader -------------------------------------------------------

variable "create_crm_loader" {
  description = "Create poc-crm-loader. Set to true once loaders/crm/Dockerfile is merged (B3)."
  type        = bool
  default     = false
}

variable "crm_loader_service_account_email" {
  description = "Email of sa-crm-loader. Set once D2 creates the service account."
  type        = string
  default     = "sa-crm-loader@gks-datalake-poc2-dev.iam.gserviceaccount.com"
}

module "run_jobs" {
  source = "../modules/run_jobs"

  project_id                       = var.project_id
  region                           = var.region
  env                              = var.env
  dbt_runner_service_account_email = var.dbt_runner_service_account_email
  image_tag                        = var.image_tag

  # B3: flip create_crm_loader to true in dev.tfvars when the image is ready
  create_crm_loader                = var.create_crm_loader
  crm_loader_service_account_email = var.crm_loader_service_account_email
}
