# E7: the team's email channel, three log-based metrics and four alert policies.
#
#   1. a poc-* workflow execution failed        (Workflows' own metric)
#   2. freshness_breach logged                  (freshness_check macro, E7)
#   3. watchdog_stale logged                    (poc-watchdog, E7)
#   4. crm_guard_tripped logged                 (CRM loader change-size guard, B5)
#
# Each policy emails the team through the notification channel below. Cloud Monitoring sends those
# emails itself: no Cloud Function and no Pub/Sub topic is involved. The three log events are JSON
# log lines with severity ERROR; Cloud Run (dbt, loader) and Workflows (watchdog) both send them to
# Cloud Logging as jsonPayload.
#
# What the email can say. Monitoring fills in variables written as ${resource.label.x} and
# ${metric.label.x} in the documentation text. In this file they are written $${...} so Terraform
# leaves them alone. The workflow id comes from the Workflows metric, and the entity (freshness) or
# source (watchdog) from a label that each log metric extracts from the log line. The error text of a
# failed workflow is NOT available to an email: the documentation says where to read it.

locals {
  has_email = var.alert_email != ""
  channels  = local.has_email ? [google_monitoring_notification_channel.team[0].id] : []

  # name => what the event means. The metric counts log lines whose jsonPayload.event matches.
  log_events = {
    freshness_breach  = "An entity is older than its freshness promise (freshness_check)."
    watchdog_stale    = "The simulator heartbeat or the case events have stopped (poc-watchdog)."
    crm_guard_tripped = "A CRM export changed too many accounts and was held (poc-crm-loader)."
  }

  # name => the jsonPayload field copied into a metric label, so the email can say WHICH entity or
  # source broke. An event not listed here has no label.
  event_labels = {
    freshness_breach = "entity"
    watchdog_stale   = "source"
  }
}

# Terraform warns, but does not fail, while no address is set: CI and CD plan with terraform.tfvars
# only, so a required variable would stop every pull request until someone commits an address.
check "alert_email_is_set" {
  assert {
    condition     = var.alert_email != ""
    error_message = "alert_email is empty: the alert policies exist but notify nobody. Set it in terraform.tfvars."
  }
}

resource "google_monitoring_notification_channel" "team" {
  count        = local.has_email ? 1 : 0
  project      = var.project_id
  display_name = "POC team email"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }
}

# ---- log-based metrics --------------------------------------------------------------------------

resource "google_logging_metric" "event" {
  for_each    = local.log_events
  project     = var.project_id
  name        = each.key
  description = each.value
  filter      = "jsonPayload.event=\"${each.key}\" AND severity>=ERROR"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"

    dynamic "labels" {
      for_each = contains(keys(local.event_labels), each.key) ? [local.event_labels[each.key]] : []
      content {
        key         = labels.value
        value_type  = "STRING"
        description = "The ${labels.value} named in the log line"
      }
    }
  }

  label_extractors = contains(keys(local.event_labels), each.key) ? {
    (local.event_labels[each.key]) = "EXTRACT(jsonPayload.${local.event_labels[each.key]})"
  } : {}
}

# ---- 1. a poc-* workflow failed -------------------------------------------------------------------

resource "google_monitoring_alert_policy" "workflow_failed" {
  project      = var.project_id
  display_name = "POC: a poc-* workflow execution failed"
  combiner     = "OR"
  severity     = "ERROR"

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      **Which workflow:** `$${resource.label.workflow_id}` finished with status FAILED.

      Its executions: https://console.cloud.google.com/workflows/workflow/us-central1/$${resource.label.workflow_id}/executions?project=${var.project_id}

      **Why it failed.** This email cannot carry the error text. Read it here, using the `<env>` in the workflow name:
      - `poc-micro-batch-<env>`: the failing step and its error are in `ops_<env>.pipeline_run_steps` (filter on the execution id).
      - `poc-full-load-<env>`: the error is in `ops_<env>.full_load_log`; drift results are in `ops_<env>.dq_result`.
      - any other `poc-*` workflow: `gcloud workflows executions describe <execution-id> --workflow=$${resource.label.workflow_id} --location=us-central1`

      **Three common causes, in the order to check:**

      **1. E11 forced-failure test (expected)**
      Someone ran the micro-batch with `{"dbt_vars": "{force_fail: true}"}`. Then this alert is intentional and `wh_<env>` should be untouched.
      ```bash
      gcloud workflows executions list poc-micro-batch-dev --location=us-central1 --limit=5
      ```

      **2. A dbt test failed (data issue)**
      A test such as `not_null` or `unique` failed, or a DQ check caught bad source data. `wh_<env>` is untouched because publish was skipped.
      ```sql
      SELECT step, status, error
      FROM ops_dev.pipeline_run_steps
      WHERE DATE(started_at) = CURRENT_DATE()
      ORDER BY started_at DESC LIMIT 10;
      ```
      The dbt artifacts of the run (once the dbt job copies them, task E3):
      ```bash
      gsutil ls gs://${var.project_id}-dbt-artifacts/dev/
      ```

      **3. An infrastructure failure (workflow step error)**
      A Cloud Run job failed to start, Cloud SQL was unreachable, or a Workflows API call timed out. Describe the execution as above.

      **A full load can also end here with DQ39 drift (exit code 3).** The full rebuild was already published; see `ops_<env>.dq_result`.

      **In every case `wh_<env>` is safe:** publish only runs when dbt exits 0.
    EOT
  }

  conditions {
    display_name = "Failed execution of a poc-* workflow"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"workflows.googleapis.com/finished_execution_count\"",
        "resource.type=\"workflows.googleapis.com/Workflow\"",
        "metric.labels.status=\"FAILED\"",
        "resource.labels.workflow_id=monitoring.regex.full_match(\"${var.workflow_name_pattern}\")",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.label.workflow_id"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.channels

  alert_strategy {
    auto_close = "1800s"
  }
}

# ---- 2, 3, 4. a logged event ----------------------------------------------------------------------

locals {
  event_policies = {
    freshness_breach = {
      title = "POC: a freshness promise is broken"
      doc   = <<-EOT
        **Which entity:** `$${metric.label.entity}` is older than its freshness promise.

        **This is a data-source issue, not a code failure.** The pipeline ran successfully but the source stopped producing new rows.

        **Immediate steps:**
        1. See how late it is (the entity is named above):
           ```sql
           SELECT entity, age_minutes, promise_minutes, age_minutes - promise_minutes AS minutes_late
           FROM ops_dev.freshness_result
           WHERE breached AND checked_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
           ORDER BY age_minutes DESC;
           ```
        2. Find its owner in `dbt/seeds/entity_registry.csv`.
        3. For `alert` / `alert_history`: check the Datastream stream and Cloud SQL are running.
        4. For `case_raw`: check the Pub/Sub subscription has no message backlog.
        5. For `crm_export`: check the CRM loader ran and the bucket has a recent export folder.

        **This is NOT an E11 forced-failure test.** E11 fails the workflow (alert policy 1), not the freshness check.
      EOT
    }
    watchdog_stale = {
      title = "POC: the source side has stopped"
      doc   = <<-EOT
        **Which source:** `$${metric.label.source}` has no recent data (`simulator` = the heartbeat row; `case_event` = Pub/Sub case events).

        **This is a source/infrastructure issue.** Either the simulator stopped writing, Cloud SQL is down, or Datastream is paused.

        **Immediate steps (check in this order):**
        1. Is Cloud SQL running?
           ```bash
           gcloud sql instances describe poc-ops-db --format="value(state)"
           # Expected: RUNNABLE
           ```
        2. Is the Datastream stream running?
           ```bash
           gcloud datastream streams describe poc-cdc-stream --location=us-central1 --format="value(state)"
           # Expected: RUNNING
           ```
        3. Is the simulator scheduler job paused?
           ```bash
           gcloud scheduler jobs describe poc-simulator --location=us-central1 --format="value(state)"
           # Expected: ENABLED
           ```
        4. For `case_event`: check the case-event publisher and the `raw_lpos.case_event` subscription.
        5. Between 20:00 and 08:00 night-off pauses the watchdog, so this alert should not fire at night. If it does, night-off did not pause it.

        **This is NOT an E11 forced-failure test.** E11 triggers alert policy 1 (workflow failed), not this one.
      EOT
    }
    crm_guard_tripped = {
      title = "POC: a CRM export was held"
      doc   = <<-EOT
        **What happened:** The CRM loader held an export because more than half of the account rows changed between two consecutive exports (DQ42).

        **This is a data-quality guard, not a pipeline failure.** The CRM step holds the export until a person approves it.

        **Immediate steps:**
        1. Find the held export (confirm the column names with `bq show raw_crm.load_log`):
           ```sql
           SELECT folder, changed_pct, row_count, loaded_at
           FROM raw_crm.load_log
           WHERE status = 'HELD'
           ORDER BY loaded_at DESC LIMIT 1;
           ```
        2. Inspect the export folder in GCS and decide if the change is legitimate.
        3. If legitimate, approve it:
           ```bash
           gcloud run jobs execute poc-crm-loader \
             --region=us-central1 \
             --args="--approve,export_ts=<timestamp>" \
             --wait
           ```
        4. If it is a data error, do not edit `raw_crm` by hand: only the loader writes it. Ask Dev 3, who owns the loader.

        **This is NOT an E11 forced-failure test.** E11 triggers alert policy 1 (workflow failed), not this one.
      EOT
    }
  }
}

resource "google_monitoring_alert_policy" "event" {
  for_each     = local.event_policies
  project      = var.project_id
  display_name = each.value.title
  combiner     = "OR"
  severity     = "ERROR"

  documentation {
    mime_type = "text/markdown"
    content   = each.value.doc
  }

  conditions {
    display_name = "${each.key} logged"

    condition_threshold {
      # Monitoring insists on a resource.type, also for log-based metrics. The dbt job and the CRM
      # loader log from Cloud Run jobs; the watchdog logs from Workflows.
      filter = join(" AND ", [
        "metric.type=\"logging.googleapis.com/user/${google_logging_metric.event[each.key].name}\"",
        "resource.type=one_of(\"cloud_run_job\",\"workflows.googleapis.com/Workflow\")",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
        # Keep the entity / source label, so each one is its own incident and is named in the email.
        group_by_fields = contains(keys(local.event_labels), each.key) ? ["metric.label.${local.event_labels[each.key]}"] : []
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.channels

  # A breach logs on every run until it is fixed. The policy opens one incident and emails once;
  # it closes itself 30 minutes after the metric stops counting. (notification_rate_limit is only
  # allowed on policies that match log lines directly, not on a metric threshold like this one.)
  alert_strategy {
    auto_close = "1800s"
  }
}
