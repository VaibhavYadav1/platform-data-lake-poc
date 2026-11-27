output "ops_dataset_id" {
  description = "Dataset id of ops_{env}."
  value       = google_bigquery_dataset.ops.dataset_id
}

output "wh_dataset_id" {
  description = "Dataset id of wh_{env}."
  value       = google_bigquery_dataset.wh.dataset_id
}

output "sec_dataset_id" {
  description = "Dataset id of sec_{env}."
  value       = google_bigquery_dataset.sec.dataset_id
}
