# D8 evidence, created in D2 (design issue #2): the first security-suite runs must already leave log
# entries, or AT-27 has nothing to link to.
#
# The sink takes BigQuery entries (blocked queries, DML, DDL) and IAM Credentials entries. Impersonating
# the writer is an IAM Credentials call, not a BigQuery one, so a BigQuery-only filter would miss D5
# case 4 (design issue #3). BigQuery data access logs are on by default; IAM Credentials' are not, so
# they are switched on below.

resource "google_bigquery_dataset" "audit_logs" {
  project     = var.project_id
  dataset_id  = var.dataset_id
  location    = var.region
  description = "BigQuery and IAM Credentials audit log entries (D8). Engineers only: entries hold callers' emails."
  labels      = { poc = "phase2", owner = "dev2", managed_by = "terraform" }
}

resource "google_logging_project_sink" "bq_audit" {
  project                = var.project_id
  name                   = var.sink_name
  destination            = "bigquery.googleapis.com/projects/${var.project_id}/datasets/${google_bigquery_dataset.audit_logs.dataset_id}"
  filter                 = "protoPayload.serviceName=\"bigquery.googleapis.com\" OR protoPayload.serviceName=\"iamcredentials.googleapis.com\""
  unique_writer_identity = true

  # One table per log, partitioned by day, instead of one table per day.
  bigquery_options {
    use_partitioned_tables = true
  }
}

# The sink's own identity writes the entries.
resource "google_bigquery_dataset_iam_member" "sink_writer" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.audit_logs.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_logging_project_sink.bq_audit.writer_identity
}

# Data access logs for IAM Credentials: generateAccessToken calls (impersonation attempts).
resource "google_project_iam_audit_config" "iamcredentials" {
  count   = var.enable_iamcredentials_data_access_logs ? 1 : 0
  project = var.project_id
  service = "iamcredentials.googleapis.com"

  audit_log_config {
    log_type = "ADMIN_READ"
  }
  audit_log_config {
    log_type = "DATA_READ"
  }
  audit_log_config {
    log_type = "DATA_WRITE"
  }
}
