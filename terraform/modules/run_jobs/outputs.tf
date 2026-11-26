output "dbt_runner_job_name" {
  description = "Full resource name of the dbt runner Cloud Run job."
  value       = google_cloud_run_v2_job.dbt_runner.name
}

output "dbt_runner_job_id" {
  description = "Resource id of the dbt runner Cloud Run job (used in workflow API calls)."
  value       = google_cloud_run_v2_job.dbt_runner.id
}

output "dbt_runner_image" {
  description = "Full image URI the job is currently pinned to."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_repo}/dbt-runner:${var.image_tag}"
}

output "crm_loader_job_name" {
  description = "Name of the poc-crm-loader Cloud Run job. Empty string if create_crm_loader is false."
  value       = var.create_crm_loader ? google_cloud_run_v2_job.crm_loader[0].name : ""
}
