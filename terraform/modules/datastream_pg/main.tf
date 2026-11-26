# A4: Datastream CDC from poc-ops-db (Cloud SQL, A1/A2) into BigQuery raw_g2, append-only.
# The datasets raw_g2 and raw_g2_parity are created in terraform/shared/datastream.tf.

data "google_project" "this" {
  project_id = var.project_id
}

# datastream_user's password (created in A1, user created in A2). It also lands in the state.
data "google_secret_manager_secret_version" "ds" {
  project = var.project_id
  secret  = "poc-ops-db-datastream"
}

# How to reach PostgreSQL: straight to the public IP (A1's authorised networks let Datastream in).
resource "google_datastream_connection_profile" "pg" {
  project               = var.project_id
  location              = var.region
  connection_profile_id = "poc-ops-db-pg"
  display_name          = "poc-ops-db-pg"
  labels                = { poc = "phase2", owner = "dev2", managed_by = "terraform" }

  postgresql_profile {
    hostname = var.pg_public_ip
    port     = 5432
    username = "datastream_user"
    password = data.google_secret_manager_secret_version.ds.secret_data
    database = "g2"

    # Cloud SQL accepts only encrypted connections (ENCRYPTED_ONLY); this also checks the server's certificate.
    # No private_connectivity block: public IP with an allowlist (A13 adds private connectivity).
    ssl_config {
      server_verification {
        ca_certificate = var.pg_server_ca_cert
      }
    }
  }

  # The Datastream API returns serverVerification as {} (it never returns ca_certificate), so the provider drops the
  # block from state and the next plan REPLACES this profile, and with it poc-cdc-stream: a new backfill into raw_g2
  # (found 25 Nov in the A8 plan). Ignore ssl_config. If the Cloud SQL server CA is ever rotated, replace the profile
  # on purpose (terraform apply -replace=...), with the stream paused.
  lifecycle {
    ignore_changes = [postgresql_profile[0].ssl_config]
  }
}

# How to reach BigQuery: same project, nothing to configure.
resource "google_datastream_connection_profile" "bq" {
  project               = var.project_id
  location              = var.region
  connection_profile_id = "poc-bq"
  display_name          = "poc-bq"
  labels                = { poc = "phase2", owner = "dev2", managed_by = "terraform" }
  bigquery_profile {}
}

# Datastream's service agent may write to raw_g2 only.
resource "google_bigquery_dataset_iam_member" "datastream_agent" {
  project    = var.project_id
  dataset_id = var.raw_dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-datastream.iam.gserviceaccount.com"
}

resource "google_datastream_stream" "cdc" {
  project       = var.project_id
  location      = var.region
  stream_id     = "poc-cdc-stream"
  display_name  = "poc-cdc-stream"
  desired_state = "RUNNING"
  labels        = { poc = "phase2", owner = "dev2", managed_by = "terraform" }

  source_config {
    source_connection_profile = google_datastream_connection_profile.pg.id
    postgresql_source_config {
      publication      = "poc_pub"
      replication_slot = "poc_slot"
      include_objects {
        postgresql_schemas {
          schema = "g2" # all 11 tables in the publication
        }
      }
    }
  }

  destination_config {
    destination_connection_profile = google_datastream_connection_profile.bq.id
    bigquery_destination_config {
      single_target_dataset {
        dataset_id = "${var.project_id}:${var.raw_dataset_id}" # tables are named g2_<table>
      }
      append_only {} # D-25: one row per change, nothing overwritten
    }
  }

  backfill_all {} # copy the existing rows first (the A3 seed)

  # The agent must be able to write to raw_g2 before the stream starts.
  depends_on = [google_bigquery_dataset_iam_member.datastream_agent]

  # Night-off (E8) pauses and resumes the stream outside Terraform.
  lifecycle {
    ignore_changes = [desired_state]
  }
}
