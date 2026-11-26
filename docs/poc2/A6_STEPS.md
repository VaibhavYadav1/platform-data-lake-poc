# A6: case-event stream, step by step

**Owner:** Dev 4  
**Days:** 3–4  
**Needs:** 0.7 (`docs/poc2/specs.md`: the Avro schema, with Dev 5)  
**Done when:** a test message lands in `raw_lpos.case_event`.  
**Design:** POC A guide section 11 (11.2 schema, 11.3 Terraform, 11.4 JSON encoding); runbook phase 7.

> Rewritten 24 Nov. The first draft of this file used a different Avro schema (`store_id`, `event_timestamp`,
> `severity`, `assigned_to`, `description`, `metadata`), clustering on a `store_id` column, and fewer IAM grants. That
> doesn't match the guide, A7's publisher, C10's staging or the acceptance tests. Use the steps below.

## What A6 builds and why

```
simulator tick (A7, A8)
  → Pub/Sub topic poc-case-events   (checks every message against the Avro schema when it's published)
  → subscription poc-case-events-to-bq   (a BigQuery subscription: Pub/Sub writes the rows itself, no loader)
  → raw_lpos.case_event
  · a message that fits the schema but BigQuery can't store: retried 5 times, then
  → dead-letter topic poc-case-events-dlq → pull subscription poc-case-events-dlq-sub (to inspect)
```

LPOS (the client's case system) can't be reached, so Pub/Sub stands in for it. The schema check at publish time
means bad messages are refused at the door; the dead-letter topic catches the rare message BigQuery still can't store.

## Before you start

- **0.7 isn't written yet** (`specs.md` says "To be written"). The guide's 11.2 schema is marked *proposed*. Build
  with it, and ask Dev 5 to confirm it (or change it) before A7 starts. Changing the schema later means replacing
  the topic's schema and the table.
- Nothing exists yet: no Pub/Sub topic, no `raw_lpos`, no `sa-simulator` (that comes with A8).

## Step 1: The Avro schema

Create `terraform/shared/schemas/case_event.avsc` with exactly the guide's 11.2 schema:

```json
{
  "type": "record",
  "name": "CaseEvent",
  "namespace": "poc.lpos",
  "fields": [
    {"name": "event_id",       "type": "string"},
    {"name": "case_id",        "type": "string"},
    {"name": "event_type",     "type": "string"},
    {"name": "event_ts",       "type": {"type": "long", "logicalType": "timestamp-micros"}},
    {"name": "g2_store_id",    "type": "string"},
    {"name": "offender_token", "type": ["null", "string"], "default": null},
    {"name": "case_status",    "type": "string"},
    {"name": "loss_amount",    "type": ["null", "double"], "default": null},
    {"name": "items_count",    "type": ["null", "int"],    "default": null}
  ]
}
```

- `event_type`: `CASE_OPENED`, `CASE_UPDATED`, `CASE_CLOSED`. `case_status`: `OPEN`, `UNDER_REVIEW`, `CLOSED`.
- `event_ts` is **microseconds** (timestamp-micros), not milliseconds like Datastream's `source_timestamp`.
- `g2_store_id` (not `store_id`): the store's G2 id, so C10 can join it to `stg_g2__stores`.
- `offender_token` is an opaque token, never a name (personal-data rule).

## Step 2: The `pubsub_bq` module

`terraform/modules/pubsub_bq/` has only a README. Add four files.

**`versions.tf`**

```hcl
terraform {
  required_providers {
    google = { source = "hashicorp/google" }
  }
}
```

**`variables.tf`**

```hcl
variable "project_id" { type = string }

variable "case_event_avsc_path" {
  description = "Path to terraform/shared/schemas/case_event.avsc."
  type        = string
}

variable "raw_dataset_id" {
  description = "Dataset for case_event (created in terraform/shared)."
  type        = string
  default     = "raw_lpos"
}
```

**`main.tf`**: the guide's 11.3, with two changes:

- `data "google_project"` looks up the project number (as in A4), instead of a `project_number` variable;
- the simulator's publisher grant waits for A8, because `sa-simulator` doesn't exist yet.

```hcl
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
    { name = "event_id",          type = "STRING",    mode = "REQUIRED" },
    { name = "case_id",           type = "STRING",    mode = "REQUIRED" },
    { name = "event_type",        type = "STRING",    mode = "REQUIRED" },
    { name = "event_ts",          type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "g2_store_id",       type = "STRING",    mode = "REQUIRED" },
    { name = "offender_token",    type = "STRING",    mode = "NULLABLE" },
    { name = "case_status",       type = "STRING",    mode = "REQUIRED" },
    { name = "loss_amount",       type = "FLOAT64",   mode = "NULLABLE" },
    { name = "items_count",       type = "INT64",     mode = "NULLABLE" },
    { name = "subscription_name", type = "STRING",    mode = "NULLABLE" },
    { name = "message_id",        type = "STRING",    mode = "NULLABLE" },
    { name = "publish_time",      type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "attributes",        type = "JSON",      mode = "NULLABLE" },
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
  name    = "poc-case-events-dlq-sub" # pull, to inspect dead letters
  topic   = google_pubsub_topic.dlq.id
  labels  = local.labels
}

# A8 adds: google_pubsub_topic_iam_member "simulator_publisher" for sa-simulator (guide 11.3).
```

**`outputs.tf`**

```hcl
output "topic_id" {
  description = "Full topic id for the publisher (CASE_TOPIC, A7/A8)."
  value       = google_pubsub_topic.case_events.id
}
```

What each piece is for:

| Resource | Why |
| --- | --- |
| Schema + `schema_settings` (JSON) | Pub/Sub refuses a message that doesn't fit the Avro schema, at publish time |
| `case_event` table, partitioned on `publish_time` | One partition per day: queries and the watchdog read only recent days. Its columns are the Avro fields plus the 4 metadata columns `write_metadata` adds |
| `to_bq` with `use_topic_schema` | Pub/Sub maps Avro fields to columns by name and writes them itself |
| `dead_letter_policy` (5 tries) | A message BigQuery can't store doesn't block the others; it moves to the DLQ |
| The 3 grants to the Pub/Sub service agent | Write to `raw_lpos`, publish to the DLQ, and acknowledge on the main subscription (both are needed for dead-lettering) |
| `depends_on` | The subscription is validated on creation: the table and the grant must exist first |

## Step 3: Call it from `terraform/shared`

Create `terraform/shared/case_events.tf`:

```hcl
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
  raw_dataset_id       = google_bigquery_dataset.raw_lpos.dataset_id # dataset first
}

output "case_topic_id" {
  value = module.pubsub_bq.topic_id
}
```

## Step 4: The Pub/Sub service agent, then plan

```bash
gcloud beta services identity create --service=pubsub.googleapis.com --project=gks-datalake-poc2-dev
cd terraform/shared
terraform init -backend-config=backend.hcl
terraform fmt -recursive .. && terraform validate
terraform plan -var-file=terraform.tfvars -out=a6.tfplan
```

Expect **10 to add** (dataset, schema, 2 topics, table, 2 subscriptions, 3 grants), 0 to change, 0 to destroy,
plus the usual `alert_email` warning. Anything touching `poc-ops-db` or `poc-cdc-stream`: stop and ask.
Have Dev 2 review the plan, then `terraform apply a6.tfplan`.

## Step 5: Two test messages (this is the "done when")

```bash
# 1) every nullable field null: no encoding question
gcloud pubsub topics publish poc-case-events --message='{"event_id":"test-0001","case_id":"CASE-000001","event_type":"CASE_OPENED","event_ts":1794996003000000,"g2_store_id":"S101","offender_token":null,"case_status":"OPEN","loss_amount":null,"items_count":null}'
# 2) nullable fields set, in Avro's wrapped JSON form (guide 11.4)
gcloud pubsub topics publish poc-case-events --message='{"event_id":"test-0002","case_id":"CASE-000001","event_type":"CASE_UPDATED","event_ts":1794996302000000,"g2_store_id":"S101","offender_token":{"string":"tok-abc"},"case_status":"UNDER_REVIEW","loss_amount":{"double":240.5},"items_count":{"int":3}}'
# if 2) is refused, try the plain form ("offender_token":"tok-abc", ...) and record which one works
```

Run in PowerShell if Git Bash mangles the quotes. Then, a few seconds later:

```sql
SELECT event_id, event_type, event_ts, offender_token, loss_amount, items_count, message_id, publish_time
FROM `gks-datalake-poc2-dev.raw_lpos.case_event`
WHERE publish_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
ORDER BY publish_time DESC;
```

Check: `event_ts` shows 2026-11-18 (microseconds understood), the nullable values in message 2 are filled, and
`message_id`/`publish_time` are set.

**Also check the schema refuses a bad message** (it must fail at publish, not land):

```bash
gcloud pubsub topics publish poc-case-events --message='{"event_id":"bad-0001"}'
```

## Step 6: Record it

- `specs.md`: which JSON form worked for nullable fields (wrapped or plain). A7's `wrap()` depends on it.
- POC A guide: 17.0 row; 5.1 status of 0.7 if Dev 5 confirmed the schema; section 21 "Avro JSON encoding" resolved.
- Commit the `.avsc`, the module, `case_events.tf` and the doc updates to `main`.

## Pitfalls

- The subscription fails to create, or writes nothing, if the table or the agent's grant isn't there first: keep the
  `depends_on`.
- `event_ts` is microseconds. A millisecond value lands in 1970.
- The test rows stay in `raw_lpos.case_event`. Use `event_id` values starting with `test-` so C10 and the acceptance
  tests can ignore them.
- Don't add the `sa-simulator` publisher grant until A8 creates that account.
