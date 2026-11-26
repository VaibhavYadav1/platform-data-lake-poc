# E4: poc-micro-batch-<env>, the workflow that runs one pipeline cycle, and the scheduler job that
# starts it. One of each per environment, so this module is applied from terraform/env (the
# night-off and morning-on workflows are one per sandbox and live in terraform/modules/workflows).
#
# The workflow definition lives in orchestration/ and is read from there.
# Prerequisites owned by other tasks: sa-orchestrator (D2), the Cloud Run job poc-dbt-runner-<env>
# (E3), poc-crm-loader (B3) and the ops_<env> dataset. Until they exist the workflow deploys but a
# run fails, so the scheduler job is created paused.

resource "google_workflows_workflow" "micro_batch" {
  project         = var.project_id
  region          = var.region
  name            = "poc-micro-batch-${var.env}"
  description     = "E4: source freshness, dbt build and publish, freshness check"
  service_account = var.orchestrator_service_account_email
  source_contents = replace(file("${path.module}/../../../orchestration/micro_batch.workflow.yaml"), "\r\n", "\n")

  # Read by the workflow with sys.get_env. A caller can still override them in the arguments.
  user_env_vars = {
    POC_ENV = var.env
  }

  labels = {
    poc = "phase2"
    env = var.env
  }
}

resource "google_cloud_scheduler_job" "micro_batch" {
  project     = var.project_id
  region      = var.region
  name        = "poc-micro-batch-${var.env}"
  description = "E4: starts the poc-micro-batch-${var.env} workflow"
  schedule    = var.schedule
  time_zone   = "UTC"
  paused      = var.schedule_paused

  http_target {
    http_method = "POST"
    uri         = "https://workflowexecutions.googleapis.com/v1/${google_workflows_workflow.micro_batch.id}/executions"
    headers     = { "Content-Type" = "application/json" }
    body        = base64encode(jsonencode({ argument = jsonencode({}) }))

    oauth_token {
      service_account_email = var.orchestrator_service_account_email
    }
  }

  # poc-night-off pauses this job and poc-morning-on resumes it. Terraform must not undo that.
  lifecycle {
    ignore_changes = [paused]
  }
}
