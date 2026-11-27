# B2/B3 in the cloud: the bucket the simulator writes the hourly CRM export to, and the job that loads it into raw_crm.
#
#   poc-source-simulator (sa-simulator)  --writes-->  gs://<project>-crm-exports/crm/export_ts=<ts>/{3 CSVs, manifest.json}
#   poc-crm-loader       (sa-crm-loader) --reads-->   the same folders; one folder is loaded once, only when its manifest exists
#
# This stack is the only owner of the poc-crm-loader job (terraform/env must not define it). The loader needs explicit
# arguments (--bucket ...): it reads no environment variables, so a start without them exits with code 2.
# poc-crm-loader-hourly (below) starts the loader alone, once an hour at minute 10 (the simulator writes at minute 0-4).
# The micro-batch workflow (run_crm_loader) also calls the job, with the same arguments. Run only one of the two
# callers at a time: two loaders at once can double an export (there is no lock yet).
#
# The bucket is separate from gks-datalake-poc2-dev-crm-test, which stays for hand tests. Nothing here touches that bucket.

variable "image_tag" {
  description = "Git commit SHA of the images to run (crm-loader, and dbt-runner in terraform/env). Cloud Build sets it as TF_VAR_image_tag; by hand: -var image_tag=<sha>."
  type        = string
  default     = "latest"  # Changed from "" to "latest" for local development
}

variable "crm_exports_retention_days" {
  description = "Days an export folder is kept. The loader only needs the newest few; raw_crm keeps every loaded export."
  type        = number
  default     = 30
}

locals {
  crm_exports_bucket = "${var.project_id}-crm-exports"
  crm_registry       = "${var.region}-docker.pkg.dev/${var.project_id}/poc"
}

resource "google_storage_bucket" "crm_exports" {
  project                     = var.project_id
  name                        = local.crm_exports_bucket
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false # exports are the source of truth for raw_crm; never deleted with the bucket

  lifecycle_rule {
    condition {
      age = var.crm_exports_retention_days
    }
    action {
      type = "Delete"
    }
  }

  labels = { poc = "phase2", managed_by = "terraform", task = "b2-b3" }
}

# The simulator checks whether an hour's manifest exists (get), writes the files and replaces a half-written folder
# (create, delete). objectUser is the smallest predefined role with all of that; it is granted on this bucket only.
resource "google_storage_bucket_iam_member" "simulator_writes_crm" {
  bucket = google_storage_bucket.crm_exports.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.simulator.email}"
}

# The loader only reads (list, get)
resource "google_storage_bucket_iam_member" "crm_loader_reads_exports" {
  bucket = google_storage_bucket.crm_exports.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${module.service_accounts.emails["sa-crm-loader"]}"
}

resource "google_cloud_run_v2_job" "crm_loader" {
  project             = var.project_id
  name                = "poc-crm-loader"
  location            = var.region
  deletion_protection = true # kept as it is on the live job; to delete the job, set false and apply first
  labels              = { poc = "phase2", managed_by = "terraform", task = "b3" }

  template {
    task_count = 1
    template {
      service_account = module.service_accounts.emails["sa-crm-loader"]
      timeout         = "900s"
      max_retries     = 0 # the next micro-batch run is the retry; the loader is safe to re-run

      containers {
        image = "${local.crm_registry}/crm-loader:${var.image_tag}"
        # The loader reads no environment variables: bucket and project are arguments. The workflow passes the same
        # arguments on every run (orchestration/micro_batch.workflow.yaml, step load_crm).
        args = ["--bucket", google_storage_bucket.crm_exports.name, "--prefix", "crm", "--project", var.project_id]

        resources {
          limits = { cpu = "1", memory = "512Mi" }
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

  depends_on = [google_storage_bucket_iam_member.crm_loader_reads_exports]
}

# The scheduler calls the job's :run endpoint as sa-orchestrator (same pattern as poc-simulator-tick)
resource "google_cloud_run_v2_job_iam_member" "orchestrator_runs_crm_loader" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.crm_loader.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.orchestrator_service_account_email}"
}

resource "google_cloud_scheduler_job" "crm_loader_hourly" {
  project     = var.project_id
  region      = var.region
  name        = "poc-crm-loader-hourly"
  description = "Loads new CRM exports into raw_crm at minute 10 of every hour. Pause: gcloud scheduler jobs pause poc-crm-loader-hourly"
  schedule    = "10 * * * *"
  time_zone   = "Etc/UTC"
  paused      = true # created paused; resumed by hand after the bucket, the image and one manual run are checked

  attempt_deadline = "60s"
  retry_config {
    retry_count = 0 # the next hour is the retry; the loader is safe to re-run
  }

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.crm_loader.name}:run"
    oauth_token {
      service_account_email = var.orchestrator_service_account_email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  lifecycle {
    ignore_changes = [paused] # pause and resume are done with gcloud
  }

  depends_on = [google_cloud_run_v2_job_iam_member.orchestrator_runs_crm_loader]
}

output "crm_exports_bucket" {
  description = "Put this in terraform/shared/terraform.tfvars as simulator_crm_bucket and in terraform/env/<env>.tfvars as crm_bucket."
  value       = google_storage_bucket.crm_exports.name
}
