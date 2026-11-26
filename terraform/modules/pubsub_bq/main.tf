data "google_project" "this" {
  project_id = var.project_id
}

locals {
  pubsub_agent = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
  labels       = { poc = "phase2", owner = "dev4", managed_by = "terraform" }
}

resource "google_pubsub_schema" "case_event" {
  project    = var.project_id
  name       = "poc-case-event"
  type       = "AVRO"
  definition = file(var.case_event_avsc_path)
}

resource "google_pubsub_topic" "case_events" {
  project = var.project_id
  name    = "poc-case-events"
  labels  = local.labels
  schema_settings {
    schema   = google_pubsub_schema.case_event.id
    encoding = "JSON"
  }
}

resource "google_pubsub_topic" "dlq" {
  project = var.project_id
  name    = "poc-case-events-dlq"
  labels  = local.labels
}

resource "google_bigquery_table" "case_event" {
  project             = var.project_id
  dataset_id          = var.raw_dataset_id
  table_id            = "case_event"
  deletion_protection = false
  time_partitioning {
    type  = "DAY"
    field = "publish_time"
  }
  schema = jsonencode([
    { name = "event_id", type = "STRING", mode = "REQUIRED" },
    { name = "case_id", type = "STRING", mode = "REQUIRED" },
    { name = "event_type", type = "STRING", mode = "REQUIRED" },
    { name = "event_ts", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "g2_store_id", type = "STRING", mode = "REQUIRED" },
    { name = "offender_token", type = "STRING", mode = "NULLABLE" },
    { name = "case_status", type = "STRING", mode = "REQUIRED" },
    { name = "loss_amount", type = "FLOAT64", mode = "NULLABLE" },
    { name = "items_count", type = "INT64", mode = "NULLABLE" },
    { name = "subscription_name", type = "STRING", mode = "NULLABLE" },
    { name = "message_id", type = "STRING", mode = "NULLABLE" },
    { name = "publish_time", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "attributes", type = "JSON", mode = "NULLABLE" },
  ])
}

# The Pub/Sub service agent writes to raw_lpos and handles dead-lettering
resource "google_bigquery_dataset_iam_member" "pubsub_writer" {
  project    = var.project_id
  dataset_id = var.raw_dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = local.pubsub_agent
}

resource "google_pubsub_topic_iam_member" "dlq_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.dlq.name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_agent
}

resource "google_pubsub_subscription" "to_bq" {
  project = var.project_id
  name    = "poc-case-events-to-bq"
  topic   = google_pubsub_topic.case_events.id
  labels  = local.labels
  bigquery_config {
    table            = "${var.project_id}.${var.raw_dataset_id}.case_event"
    use_topic_schema = true
    write_metadata   = true
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dlq.id
    max_delivery_attempts = 5
  }
  depends_on = [google_bigquery_dataset_iam_member.pubsub_writer, google_bigquery_table.case_event]
}

resource "google_pubsub_subscription_iam_member" "main_subscriber" {
  project      = var.project_id
  subscription = google_pubsub_subscription.to_bq.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent
}

resource "google_pubsub_subscription" "dlq_sub" {
  project = var.project_id
  name    = "poc-case-events-dlq-sub"
  topic   = google_pubsub_topic.dlq.id
  labels  = local.labels
}

# A8 adds: google_pubsub_topic_iam_member "simulator_publisher" for sa-simulator (guide 11.3).
