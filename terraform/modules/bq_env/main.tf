# The ops_<env> dataset for one environment (dev or int). Applied from terraform/env, once per
# environment.
#
# Only the dataset is created here. The tables inside it are created by whatever writes to them, on
# its first run, so each writer owns its own schema:
#   pipeline_run_steps                  poc-micro-batch-<env> workflow   (ensure_log_table)
#   full_load_log                       poc-full-load-<env> workflow     (ensure_log_table)
#   dq_result                           full_load.py                     (ops_tables.sql)
#   publish_log, publish_policy_state   publish.py                       (ensure_ops_tables)
#   freshness_result                    the freshness_check dbt macro
# None of them can create the dataset, so it must exist before the first run.

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
