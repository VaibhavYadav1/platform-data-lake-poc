# E6: poc-full-load-<env>, the workflow that runs the daily full rebuild, and the scheduler job
# that starts it. One of each per environment in var.full_load_environments.
#
# The workflow definition lives in orchestration/ and is read from there.
# Prerequisites: sa-orchestrator (D2), poc-dbt-runner-<env> (E3), publish.py with --all (E5),
# the ops_<env> dataset. The scheduler job is created paused (var.schedule_paused): run the
# workflow by hand once, then set the variable to false and apply.
#
# poc-night-off and poc-morning-on do NOT touch these jobs. The full load runs at 20:15, AFTER
# night-off has paused the micro-batch, and it reads only BigQuery.

resource "google_workflows_workflow" "full_load" {
  for_each = var.full_load_environments

  project         = var.project_id
  region          = var.region
  name            = "poc-full-load-${each.key}"
  description     = "E6: nightly full rebuild with DQ39 drift check and personal-data scan (DQ41)"
  service_account = var.orchestrator_service_account_email
  source_contents = replace(file("${path.module}/../../../orchestration/full_load.workflow.yaml"), "\r\n", "\n")

  # Read by the workflow with sys.get_env. A caller can still override them in the arguments.
  user_env_vars = {
    POC_ENV     = each.key
    POC_PROJECT = var.project_id
  }

  labels = {
    poc = "phase2"
    env = each.key
  }
}

resource "google_cloud_scheduler_job" "full_load" {
  for_each = var.full_load_environments

  project     = var.project_id
  region      = var.region
  name        = "poc-full-load-${each.key}"
  description = "E6: starts the poc-full-load-${each.key} workflow, Monday to Friday after night-off"
  schedule    = var.full_load_schedule
  time_zone   = var.schedule_time_zone
  paused      = var.schedule_paused

  http_target {
    http_method = "POST"
    uri         = "https://workflowexecutions.googleapis.com/v1/${google_workflows_workflow.full_load[each.key].id}/executions"
    headers     = { "Content-Type" = "application/json" }
    body        = base64encode(jsonencode({ argument = jsonencode({}) }))

    oauth_token {
      service_account_email = var.orchestrator_service_account_email
    }
  }
}
