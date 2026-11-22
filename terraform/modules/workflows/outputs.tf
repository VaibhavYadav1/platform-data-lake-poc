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
