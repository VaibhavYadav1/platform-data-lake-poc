# A6: case events (LPOS stand-in). One for the whole sandbox, like raw_g2.
resource "google_bigquery_dataset" "raw_lpos" {
  project     = var.project_id
  dataset_id  = "raw_lpos"
  location    = var.region
  description = "Case events from Pub/Sub (A6): one row per message, duplicates included."
  labels      = { poc = "phase2", owner = "dev4", managed_by = "terraform" }
}

module "pubsub_bq" {
  source               = "../modules/pubsub_bq"
  project_id           = var.project_id
  case_event_avsc_path = "${path.module}/schemas/case_event.avsc"
  raw_dataset_id       = google_bigquery_dataset.raw_lpos.dataset_id
}

output "case_topic_id" {
  value = module.pubsub_bq.topic_id
}
