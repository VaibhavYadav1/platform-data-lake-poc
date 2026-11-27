# E3: the Cloud Run job that runs dbt and publish.py, once per environment. The workflows start it with container
# arguments (orchestration/micro_batch.workflow.yaml, full_load.workflow.yaml); the commands are in dbt/entrypoint.sh.
#
# The image is built from dbt/Dockerfile on every merge to main (cloudbuild/main.yaml) and tagged with the commit SHA.
# The job runs as sa-dwh-writer-<env> (terraform/env/security.tf).

variable "image_tag" {
  description = "Git commit SHA of the dbt-runner image. Cloud Build sets it as TF_VAR_image_tag; by hand: -var image_tag=<sha>."
  type        = string
  default     = "latest"  # Changed from "" to "latest" for local development
}

resource "google_cloud_run_v2_job" "dbt_runner" {
  project             = var.project_id
  name                = "poc-dbt-runner-${var.env}"
  location            = var.region
  deletion_protection = false
  labels              = { poc = "phase2", env = var.env, managed_by = "terraform", task = "e3" }

  template {
    task_count = 1
    template {
      service_account = "sa-dwh-writer-${var.env}@${var.project_id}.iam.gserviceaccount.com"
      timeout         = "900s" # the workflow waits 1200s (dbt_timeout_seconds)
      max_retries     = 0      # the workflow decides what a failure means

      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/poc/dbt-runner:${var.image_tag}"

        resources {
          limits = { cpu = "2", memory = "2Gi" }
        }

        dynamic "env" {
          for_each = {
            DBT_TARGET  = var.env
            GCP_PROJECT = var.project_id
            POC_PROJECT = var.project_id
          }
          content {
            name  = env.key
            value = env.value
          }
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = var.image_tag != ""
      error_message = "image_tag cannot be empty. Set via -var image_tag=<sha> or use default 'latest'."
    }
  }
}
