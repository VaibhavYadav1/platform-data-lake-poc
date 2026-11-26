variable "project_id" {
  description = "GCP project that runs the Cloud Run job."
  type        = string
}

variable "region" {
  description = "Region for the Cloud Run job and Artifact Registry."
  type        = string
  default     = "us-central1"
}

variable "env" {
  description = "Environment name: dev or int. Appended to the job name and used as DBT_TARGET."
  type        = string
}

variable "dbt_runner_service_account_email" {
  description = "Email of sa-dwh-writer-{env}. The job runs as this identity."
  type        = string
}

variable "image_tag" {
  description = <<-EOT
    Docker image tag for the dbt runner image.
    Cloud Build sets this to the commit SHA on every merge (TF_VAR_image_tag=$COMMIT_SHA).
    Use "latest" before the first merge that builds the image.
  EOT
  type        = string
  default     = "latest"
}

variable "artifact_repo" {
  description = "Artifact Registry repository name that holds the dbt-runner image."
  type        = string
  default     = "poc"
}

# ---- B3: CRM loader -------------------------------------------------------------------------

variable "create_crm_loader" {
  description = "Create the poc-crm-loader Cloud Run job. Set to false until loaders/crm/Dockerfile is merged (B3)."
  type        = bool
  default     = false
}

variable "crm_loader_service_account_email" {
  description = "Email of sa-crm-loader. Has object viewer on the CRM bucket and editor on raw_crm. Leave empty to use the default compute service account."
  type        = string
  default     = ""
}

variable "crm_loader_image_tag" {
  description = "Docker image tag for the crm-loader image. Use 'latest' until Cloud Build builds it (B3)."
  type        = string
  default     = "latest"
}
