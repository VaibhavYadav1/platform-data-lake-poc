output "ops_dataset_id" {
  description = "Dataset id of ops_{env}."
  value       = google_bigquery_dataset.ops.dataset_id
}
