output "night_off_workflow_id" {
  description = "Resource id of the poc-night-off workflow."
  value       = google_workflows_workflow.night_off.id
}

output "morning_on_workflow_id" {
  description = "Resource id of the poc-morning-on workflow."
  value       = google_workflows_workflow.morning_on.id
}

output "watchdog_workflow_id" {
  description = "Resource id of the poc-watchdog workflow."
  value       = google_workflows_workflow.watchdog.id
}

output "full_load_workflow_ids" {
  description = "Map of environment name to poc-full-load workflow resource id."
  value       = { for env, wf in google_workflows_workflow.full_load : env => wf.id }
}

output "full_load_scheduler_job_ids" {
  description = "Map of environment name to poc-full-load scheduler job resource id."
  value       = { for env, job in google_cloud_scheduler_job.full_load : env => job.id }
}
