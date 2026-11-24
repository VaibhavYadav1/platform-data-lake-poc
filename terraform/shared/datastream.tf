# A4: CDC from poc-ops-db into raw_g2. Datastream creates the tables, not the datasets.
# One of each for the whole sandbox: POC C, POC D and the watchdog all read raw_g2.

resource "google_bigquery_dataset" "raw_g2" {
  project     = var.project_id
  dataset_id  = "raw_g2"
  location    = var.region
  description = "Datastream append-only change rows from poc-ops-db (A4). One table per g2 table: g2_<table>."
  labels      = { poc = "phase2", owner = "dev2", managed_by = "terraform" }
}

resource "google_bigquery_dataset" "raw_g2_parity" {
  project     = var.project_id
  dataset_id  = "raw_g2_parity"
  location    = var.region
  description = "Frozen snapshot of raw_g2 right after the backfill (A4); POC C parity (C4) compares against it."
  labels      = { poc = "phase2", owner = "dev2", managed_by = "terraform" }
}

module "datastream_pg" {
  source            = "../modules/datastream_pg"
  project_id        = var.project_id
  region            = var.region
  pg_public_ip      = module.cloudsql_g2.public_ip
  pg_server_ca_cert = module.cloudsql_g2.server_ca_cert
  raw_dataset_id    = google_bigquery_dataset.raw_g2.dataset_id # also makes the dataset come first
}

output "cdc_stream_id" {
  value = module.datastream_pg.stream_id
}
