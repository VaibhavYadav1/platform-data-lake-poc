# E8: poc-night-off and poc-morning-on, and the scheduler jobs that start them.
# The workflow definitions live in orchestration/ and are read from there.
#
# Terraform must not undo what these workflows do. The resources they change are defined in
# other modules, and each needs ignore_changes there:
#   - Datastream stream (datastream_pg):  desired_state
#   - Cloud SQL instance (cloudsql_g2):   settings[0].activation_policy
#   - paused scheduler jobs (simulator, micro-batch, watchdog): paused

locals {
  night_off_args = {
    location       = var.region
    sql_instance   = var.sql_instance_name
    stream_id      = var.datastream_stream_id
    scheduler_jobs = concat(var.simulator_scheduler_jobs, var.delayed_scheduler_jobs)
  }

  morning_on_args = {
    location       = var.region
    sql_instance   = var.sql_instance_name
    stream_id      = var.datastream_stream_id
    simulator_jobs = var.simulator_scheduler_jobs
    delayed_jobs   = var.delayed_scheduler_jobs
    delay_seconds  = var.morning_delay_seconds
  }
}

resource "google_workflows_workflow" "night_off" {
  project         = var.project_id
  region          = var.region
  name            = "poc-night-off"
  description     = "E8: pause scheduler jobs, pause the Datastream stream, stop Cloud SQL (in that order)"
  service_account = var.orchestrator_service_account_email
  source_contents = replace(file("${path.module}/../../../orchestration/night_off.workflow.yaml"), "\r\n", "\n")

  labels = {
    poc = "phase2"
  }
}

resource "google_workflows_workflow" "morning_on" {
  project         = var.project_id
  region          = var.region
  name            = "poc-morning-on"
  description     = "E8: start Cloud SQL, resume the stream and simulator, then micro-batch and watchdog"
  service_account = var.orchestrator_service_account_email
  source_contents = replace(file("${path.module}/../../../orchestration/morning_on.workflow.yaml"), "\r\n", "\n")

  labels = {
    poc = "phase2"
  }
}

resource "google_cloud_scheduler_job" "night_off" {
  project     = var.project_id
  region      = var.region
  name        = "poc-night-off"
  description = "E8: runs the poc-night-off workflow, Monday to Friday"
  schedule    = var.night_off_schedule
  time_zone   = var.schedule_time_zone
  paused      = var.schedule_paused

  http_target {
    http_method = "POST"
    uri         = "https://workflowexecutions.googleapis.com/v1/${google_workflows_workflow.night_off.id}/executions"
    headers     = { "Content-Type" = "application/json" }
    body        = base64encode(jsonencode({ argument = jsonencode(local.night_off_args) }))

    oauth_token {
      service_account_email = var.orchestrator_service_account_email
    }
  }
}

resource "google_cloud_scheduler_job" "morning_on" {
  project     = var.project_id
  region      = var.region
  name        = "poc-morning-on"
  description = "E8: runs the poc-morning-on workflow, Monday to Friday"
  schedule    = var.morning_on_schedule
  time_zone   = var.schedule_time_zone
  paused      = var.schedule_paused

  http_target {
    http_method = "POST"
    uri         = "https://workflowexecutions.googleapis.com/v1/${google_workflows_workflow.morning_on.id}/executions"
    headers     = { "Content-Type" = "application/json" }
    body        = base64encode(jsonencode({ argument = jsonencode(local.morning_on_args) }))

    oauth_token {
      service_account_email = var.orchestrator_service_account_email
    }
  }
}

# Rights sa-orchestrator needs for E8. Project level: the sandbox holds only POC resources.
resource "google_project_iam_member" "orchestrator_e8" {
  for_each = var.manage_orchestrator_iam ? toset([
    "roles/workflows.invoker",    # the scheduler jobs start workflow executions as this account
    "roles/cloudscheduler.admin", # pause and resume scheduler jobs
    "roles/datastream.admin",     # pause and resume the stream
    "roles/cloudsql.editor",      # stop and start the instance
    "roles/logging.logWriter",
    # E4 micro-batch: run Cloud Run jobs with container arguments, and write pipeline_run_steps.
    "roles/run.developer",
    "roles/bigquery.dataEditor",
  ]) : toset([])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${var.orchestrator_service_account_email}"
}
