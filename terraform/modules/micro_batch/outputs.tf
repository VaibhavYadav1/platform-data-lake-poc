output "workflow_id" {
  description = "Resource id of the poc-micro-batch workflow."
  value       = google_workflows_workflow.micro_batch.id
}

output "scheduler_job_id" {
  description = "Resource id of the scheduler job that starts the workflow."
  value       = google_cloud_scheduler_job.micro_batch.id
}
