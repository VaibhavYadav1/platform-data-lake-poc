# Service account the PR trigger runs as. New projects have no default Cloud Build account,
# so the trigger must name one. CI only plans: read access to the project, never write access
# to infrastructure. The dbt CI build writes only to the dbt_pr_* datasets it creates.

variable "tfstate_bucket" {
  description = "Terraform state bucket. Created by hand once (see the runbook)."
  type        = string
  default     = "gks-datalake-poc2-dev-tfstate"
}

resource "google_service_account" "cloudbuild" {
  project      = var.project_id
  account_id   = "sa-cloudbuild"
  display_name = "Cloud Build (CI and CD)"
}

resource "google_project_iam_member" "cloudbuild" {
  for_each = toset([
    "roles/logging.logWriter",    # build logs (pr.yaml uses CLOUD_LOGGING_ONLY)
    "roles/viewer",               # terraform plan refreshes state by reading resources
    "roles/bigquery.dataEditor",  # dbt build into dbt_pr_* datasets; bq mk creates them
    "roles/bigquery.jobUser",     # run BigQuery jobs
    "roles/iam.securityReviewer", # plan reads IAM policies
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.cloudbuild.email}"
}

# State bucket: plan reads state; -lock=false in pr.yaml avoids writes, but init still needs list/get.
resource "google_storage_bucket_iam_member" "cloudbuild_state" {
  bucket = var.tfstate_bucket
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.cloudbuild.email}"
}
