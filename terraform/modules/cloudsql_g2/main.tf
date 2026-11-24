# A1: Cloud SQL poc-ops-db, the stand-in for StorePort G2 (PostgreSQL 16, logical decoding on).
# The schema, users, publication and slot are created by the A2 bootstrap, not here.

# 1) Read Datastream's fixed outbound IPs in this region. Read-only: a "data" source creates nothing.
data "google_datastream_static_ips" "ds" {
  project  = var.project_id
  location = var.region
}
# 2) The server.
resource "google_sql_database_instance" "g2" {
  project             = var.project_id
  name                = "poc-ops-db"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = false # sandbox: terraform destroy must be able to remove it

  settings {
    edition           = "ENTERPRISE" # shared-core tiers (db-f1-micro) need Enterprise, not Enterprise Plus
    tier              = var.tier
    availability_type = "ZONAL" # one zone, no standby copy: half the price
    user_labels       = { poc = "phase2", managed_by = "terraform" }

    # Turns the WAL into readable row changes. Without it there is no CDC for Datastream.
    database_flags {
      name  = "cloudsql.logical_decoding"
      value = "on"
    }

    backup_configuration {
      enabled = false # sandbox: the data can always be re-seeded from the baseline
    }

    ip_configuration {
      ipv4_enabled = true             # public IP, so Datastream can reach it
      ssl_mode     = "ENCRYPTED_ONLY" # refuse any unencrypted connection

      # The firewall: only Datastream's IPs may connect directly.
      dynamic "authorized_networks" {
        for_each = data.google_datastream_static_ips.ds.static_ips
        content {
          name  = "datastream-${authorized_networks.key}"
          value = "${authorized_networks.value}/32"
        }
      }
    }
  }

  # Night-off (E8) stops and starts the instance outside Terraform.
  # Without this, the next apply would see "stopped" and start it again.
  lifecycle {
    ignore_changes = [settings[0].activation_policy]
  }
}
# 3) The empty database the schema goes into (A2).
resource "google_sql_database" "g2" {
  project  = var.project_id
  instance = google_sql_database_instance.g2.name
  name     = "g2"
}
# 4) Three passwords: the admin (bootstrap) and the two logins A2 creates.
locals {
  db_logins = toset(["postgres", "datastream", "simulator"])
}

resource "random_password" "db" {
  for_each = local.db_logins
  length   = 32
  special  = false # letters and digits only: safe in connection strings
}

# Cloud SQL creates a "postgres" user with no usable password. This sets it.
resource "google_sql_user" "postgres" {
  project  = var.project_id
  instance = google_sql_database_instance.g2.name
  name     = "postgres"
  password = random_password.db["postgres"].result
}
# 5) Store each password in Secret Manager. Programs read them from there, never from code or files.
resource "google_secret_manager_secret" "db" {
  for_each  = local.db_logins
  project   = var.project_id
  secret_id = "poc-ops-db-${each.key}" # poc-ops-db-postgres, -datastream, -simulator

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db" {
  for_each    = local.db_logins
  secret      = google_secret_manager_secret.db[each.key].id
  secret_data = random_password.db[each.key].result
}
