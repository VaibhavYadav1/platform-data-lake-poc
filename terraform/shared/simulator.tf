# A8/A9: the source simulator in the cloud (POC A guide 10.6, docs/poc2/A8_STEPS.md).
# One for the whole sandbox, like the stream, so it lives in shared, not env.
#
#   Cloud Scheduler poc-simulator-tick (*/5, as sa-orchestrator, created PAUSED)
#     -> Cloud Run job poc-source-simulator (as sa-simulator): G2 changes, case events (A7), CRM (B2), heartbeat
#
# Prerequisites: poc-ops-db and its simulator secret (A1, A2), the image in Artifact Registry repo "poc"
# (built by hand from simulator/ until CD, E2), sa-orchestrator (by hand until D2).
#
# A9: sim_g2_datalake dataset for wheel and wheel_event data (task A9).
# Tables (wheel, wheel_event, derived_alert) are created by simulator/create_sim_g2_datalake.py

resource "google_bigquery_dataset" "sim_g2_datalake" {
  project     = var.project_id
  dataset_id  = "sim_g2_datalake"
  location    = var.region
  description = "Simulated G2 data lake (A9): wheel, wheel_event, derived_alert. Stand-in for the client's g2_datalake."
  labels      = { poc = "a", layer = "source", source = "sim_g2_datalake", managed_by = "terraform" }
}

variable "simulator_image" {
  description = "poc-source-simulator image, built from simulator/: us-central1-docker.pkg.dev/<project>/poc/poc-source-simulator:<git sha>."
  type        = string
}

variable "simulator_rate" {
  description = "Scales the changes per tick (guide 10.5). 1.0 = normal, 0 = heartbeat only."
  type        = number
  default     = 1.0
  validation {
    condition     = var.simulator_rate >= 0 && var.simulator_rate <= 5
    error_message = "simulator_rate must be between 0 and 5."
  }
}

variable "simulator_case_topic" {
  description = "Full Pub/Sub topic name for case events, once A6 and A7 are in. Empty = case events off."
  type        = string
  default     = ""
}

variable "simulator_crm_bucket" {
  description = "CRM landing bucket for the hourly export (B2): the crm_exports bucket of crm_exports.tf. Empty = CRM export off."
  type        = string
  default     = ""
}

resource "google_service_account" "simulator" {
  project      = var.project_id
  account_id   = "sa-simulator"
  display_name = "POC source simulator (A8)"
  description  = "Runs poc-source-simulator: writes G2 in poc-ops-db, publishes case events, writes CRM exports."
}

# A9: simulator writes wheel and wheel_event to sim_g2_datalake
resource "google_bigquery_dataset_iam_member" "simulator_writes_datalake" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.sim_g2_datalake.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.simulator.email}"
}

# Cloud SQL connection (the job's /cloudsql socket) and the simulator_user password
resource "google_project_iam_member" "simulator_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.simulator.email}"
}

resource "google_secret_manager_secret_iam_member" "simulator_password" {
  project   = var.project_id
  secret_id = module.cloudsql_g2.secret_ids["simulator"]
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.simulator.email}"
}

resource "google_cloud_run_v2_job" "simulator" {
  project             = var.project_id
  name                = "poc-source-simulator"
  location            = var.region
  deletion_protection = false
  labels              = { poc = "phase2", owner = "dev3", managed_by = "terraform", task = "a8" }

  template {
    task_count = 1
    template {
      service_account = google_service_account.simulator.email
      timeout         = "240s" # finish well inside the 5-minute interval
      max_retries     = 0      # the next tick is the retry

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [module.cloudsql_g2.connection_name]
        }
      }

      containers {
        image = var.simulator_image
        args  = ["tick"]

        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }

        # Guide 10.6 used the Cloud SQL Python connector (PG_INSTANCE, PG_SECRET). As built: Cloud Run opens the
        # socket and injects the password, so the simulator connects with plain psycopg.
        dynamic "env" {
          for_each = {
            MODE         = "tick"
            RATE         = tostring(var.simulator_rate)
            PG_HOST      = "/cloudsql/${module.cloudsql_g2.connection_name}"
            PG_DB        = "g2"
            PG_USER      = "simulator_user"
            CASE_TOPIC   = var.simulator_case_topic
            CRM_BUCKET   = var.simulator_crm_bucket
            G2DL_PROJECT = var.project_id
            G2DL_DATASET = google_bigquery_dataset.sim_g2_datalake.dataset_id
          }
          content {
            name  = env.key
            value = env.value
          }
        }

        env {
          name = "PG_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = module.cloudsql_g2.secret_ids["simulator"]
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [
    google_project_iam_member.simulator_sql_client,
    google_secret_manager_secret_iam_member.simulator_password,
    google_storage_bucket_iam_member.simulator_writes_crm,
    google_bigquery_dataset_iam_member.simulator_writes_datalake,
  ]
}

# The scheduler calls the job's :run endpoint as sa-orchestrator
resource "google_cloud_run_v2_job_iam_member" "orchestrator_runs_simulator" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.simulator.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.orchestrator_service_account_email}"
}

resource "google_cloud_scheduler_job" "simulator_tick" {
  project     = var.project_id
  region      = var.region
  name        = "poc-simulator-tick"
  description = "A8: one simulator tick every 5 minutes. Pause switch: gcloud scheduler jobs pause poc-simulator-tick"
  schedule    = "*/5 * * * *"
  time_zone   = "Etc/UTC"
  paused      = true # switched on by hand after the first tick is checked (A8_STEPS.md)

  attempt_deadline = "60s"
  retry_config {
    retry_count = 0 # the next tick is the retry
  }

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.simulator.name}:run"
    oauth_token {
      service_account_email = var.orchestrator_service_account_email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  # The pause switch, night-off/morning-on (E8) and AT-15 pause and resume it outside Terraform
  lifecycle {
    ignore_changes = [paused]
  }

  depends_on = [google_cloud_run_v2_job_iam_member.orchestrator_runs_simulator]
}

output "simulator_service_account" {
  value = google_service_account.simulator.email
}

output "sim_g2_datalake_dataset_id" {
  value = google_bigquery_dataset.sim_g2_datalake.dataset_id
}
