output "dataset_id" {
  value = google_bigquery_dataset.audit_logs.dataset_id
}

output "writer_identity" {
  description = "The sink's identity; it has editor on the audit dataset."
  value       = google_logging_project_sink.bq_audit.writer_identity
}
