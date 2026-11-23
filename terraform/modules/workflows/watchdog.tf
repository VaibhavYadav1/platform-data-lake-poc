# E7: poc-watchdog, and the scheduler job that starts it every 5 minutes.
# One for the whole sandbox: raw_g2 and raw_lpos are shared by every environment.
# The definition lives in orchestration/ and is read from there.
#
# Created paused (var.schedule_paused, shared with night-off). Run the workflow by hand once,
# then set the variable to false. poc-night-off pauses this job and poc-morning-on resumes it,
# so Terraform ignores later changes to `paused`.

resource "google_workflows_workflow" "watchdog" {
  project         = var.project_id
  region          = var.region
  name            = "poc-watchdog"
  description     = "E7: logs watchdog_stale when the simulator heartbeat or the case events stop"
  service_account = var.orchestrator_service_account_email
  source_contents = replace(file("${path.module}/../../../orchestration/watchdog.workflow.yaml"), "\r\n", "\n")

  labels = {
    poc = "phase2"
  }
}

resource "google_cloud_scheduler_job" "watchdog" {
  project     = var.project_id
  region      = var.region
  name        = "poc-watchdog"
  description = "E7: runs the poc-watchdog workflow every ${var.watchdog_interval_minutes} minutes"
  schedule    = "*/${var.watchdog_interval_minutes} * * * *"
  time_zone   = "UTC"
  paused      = var.schedule_paused

  http_target {
    http_method = "POST"
    uri         = "https://workflowexecutions.googleapis.com/v1/${google_workflows_workflow.watchdog.id}/executions"
    headers     = { "Content-Type" = "application/json" }
    body        = base64encode(jsonencode({ argument = jsonencode({}) }))

    oauth_token {
      service_account_email = var.orchestrator_service_account_email
    }
  }

  lifecycle {
    ignore_changes = [paused]
  }
}
