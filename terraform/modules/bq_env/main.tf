# BigQuery datasets for one environment (dev or int). Applied from terraform/env, once per
# environment.
#
# ops_<env>: Operational tables created by their writers on first run:
#   pipeline_run_steps                  poc-micro-batch-<env> workflow   (ensure_log_table)
#   full_load_log                       poc-full-load-<env> workflow     (ensure_log_table)
#   dq_result                           full_load.py                     (ops_tables.sql)
#   publish_log, publish_policy_state   publish.py                       (ensure_ops_tables)
#   freshness_result                    the freshness_check dbt macro
#
# wh_<env>: Data warehouse tables (published from build_<env> by publish.py)
# sec_<env>: Security tables (map_tenant_access, etc.)

resource "google_bigquery_dataset" "ops" {
  project                    = var.project_id
  dataset_id                 = "ops_${var.env}"
  location                   = var.region
  delete_contents_on_destroy = true

  labels = {
    poc        = "phase2"
    env        = var.env
    managed_by = "terraform"
  }
}

resource "google_bigquery_dataset" "wh" {
  project                    = var.project_id
  dataset_id                 = "wh_${var.env}"
  location                   = var.region
  delete_contents_on_destroy = true

  labels = {
    poc        = "phase2"
    env        = var.env
    managed_by = "terraform"
  }
}

resource "google_bigquery_dataset" "sec" {
  project                    = var.project_id
  dataset_id                 = "sec_${var.env}"
  location                   = var.region
  delete_contents_on_destroy = true

  labels = {
    poc        = "phase2"
    env        = var.env
    managed_by = "terraform"
  }
}
