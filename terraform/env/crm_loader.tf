# B3: Cloud Run job poc-crm-loader.
# One job for the whole sandbox (not per environment) because raw_crm is a shared dataset.
# The micro-batch workflow in dev starts it on every cycle; int skips it (run_crm_loader=false).
#
# The image is built from loaders/crm/Dockerfile on every merge to main (cloudbuild/main.yaml).
# Until the Dockerfile exists, the job uses a placeholder image (python:3.12-slim).

variable "crm_loader_image_tag" {
  description = "Docker image tag for the crm-loader image. Cloud Build sets it as TF_VAR_image_tag. Use 'latest' until the first real image is built."
  type        = string
  default     = "latest"
}

resource "google_cloud_run_v2_job" "crm_loader" {
  project             = var.project_id
  name                = "poc-crm-loader"
  location            = var.region
  deletion_protection = false
  labels              = { poc = "phase2", managed_by = "terraform", task = "b3" }

  template {
    task_count = 1
    template {
      service_account = "sa-crm-loader@${var.project_id}.iam.gserviceaccount.com"
      timeout         = "900s"
      max_retries     = 0

      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/poc/crm-loader:${var.crm_loader_image_tag}"

        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }

        dynamic "env" {
          for_each = {
            GCP_PROJECT = var.project_id
            CRM_BUCKET  = "${var.project_id}-crm-exports"
          }
          content {
            name  = env.key
            value = env.value
          }
        }
      }
    }
  }
}
