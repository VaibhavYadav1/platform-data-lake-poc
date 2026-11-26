# E3: Cloud Run job poc-dbt-runner-{env}
#
# This job runs dbt and publish.py inside one container so publish only ever
# sees the build it follows. The workflow (E4) starts it by calling the Cloud
# Run Jobs API; the job itself decides what to do based on the args it receives:
#
#   microbatch          dbt build --exclude tag:daily, then publish.py
#   fullload            daily full rebuild + DQ39 + publish --all + DQ41 scan
#   dbt <args>          pass-through to dbt (used for one-off runs)
#
# Image is built and pushed by Cloud Build (main.yaml) on every merge.
# The image tag is the commit SHA, so every execution traces back to its code.
# Terraform receives it as var.image_tag (TF_VAR_image_tag in Cloud Build).
#
# "Create if not exists" behaviour: Terraform's google_cloud_run_v2_job always
# creates the job on first apply and updates it on subsequent applies when the
# image tag or any other attribute changes. There is no manual step needed.

resource "google_cloud_run_v2_job" "dbt_runner" {
  project  = var.project_id
  location = var.region
  name     = "poc-dbt-runner-${var.env}"

  # false: allows Terraform to destroy and recreate the job when the image changes.
  # A tainted job (e.g. from a failed first apply) can only be replaced if this is false.
  deletion_protection = false

  labels = {
    poc        = "phase2"
    env        = var.env
    managed_by = "terraform"
  }

  template {
    labels = {
      poc = "phase2"
      env = var.env
    }

    template {
      # Service account that owns the dbt build and publish steps.
      # It has viewer on raw_*, editor on build/wh/sec/ops/dq datasets,
      # and the custom role for row-access policies (D2).
      service_account = var.dbt_runner_service_account_email

      # 15-minute hard limit. The workflow sets its own timeout slightly longer
      # so it always sees the job's exit code rather than timing out first.
      timeout = "900s"

      # No retries: a failed build must not silently re-run; the workflow
      # decides how to handle the failure and alerts the team.
      max_retries = 0

      containers {
        # Image built by Cloud Build on every merge (main.yaml, image-dbt-runner step).
        # Tag is the commit SHA so the job is always at the exact merged version.
        # On first apply, before any merge has built the image, set
        # image_tag = "latest" in terraform.tfvars and push an image by hand once
        # (see E3 task notes in the execution plan).
        image = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_repo}/dbt-runner:${var.image_tag}"

        # entrypoint.sh reads DBT_TARGET to pick the right profiles.yml target,
        # and POC_PROJECT for BigQuery dataset references.
        env {
          name  = "DBT_TARGET"
          value = var.env
        }
        env {
          name  = "POC_PROJECT"
          value = var.project_id
        }
        env {
          name  = "GCP_PROJECT"
          value = var.project_id
        }

        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }
      }
    }
  }
}

# B3: Cloud Run job poc-crm-loader
#
# Loads new CRM export folders from GCS into raw_crm landing tables.
# One job for the whole sandbox (not per environment) because raw_crm is a
# shared dataset — dev and int both read from it. The micro-batch workflow
# in dev starts it on every cycle; int skips it (run_crm_loader = false).
#
# The job is created even when loaders/crm/Dockerfile hasn't been merged yet.
# Cloud Build's image-crm-loader step is currently commented out in main.yaml
# (B3 not built), so the image doesn't exist yet. Set crm_loader_image_tag =
# "latest" until the first image is pushed, then Cloud Build updates it.
#
# Note: poc-crm-loader has no {env} suffix because it is shared.

resource "google_cloud_run_v2_job" "crm_loader" {
  count    = var.create_crm_loader ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = "poc-crm-loader"

  deletion_protection = false

  labels = {
    poc        = "phase2"
    managed_by = "terraform"
  }

  template {
    labels = {
      poc = "phase2"
    }

    template {
      service_account = var.crm_loader_service_account_email != "" ? var.crm_loader_service_account_email : null
      timeout         = "900s" # 15 minutes; the workflow waits up to crm_timeout_seconds
      max_retries     = 0      # same reason as dbt_runner: workflow handles failures

      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_repo}/crm-loader:${var.crm_loader_image_tag}"

        env {
          name  = "GCP_PROJECT"
          value = var.project_id
        }
        env {
          name  = "CRM_BUCKET"
          value = "${var.project_id}-crm-exports"
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }
    }
  }
}
