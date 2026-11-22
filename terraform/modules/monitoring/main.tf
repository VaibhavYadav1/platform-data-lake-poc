# E7: the team's email channel, three log-based metrics and four alert policies.
#
#   1. a poc-* workflow execution failed        (Workflows' own metric)
#   2. freshness_breach logged                  (freshness_check macro, E7)
#   3. watchdog_stale logged                    (poc-watchdog, E7)
#   4. crm_guard_tripped logged                 (CRM loader change-size guard, B5)
#
# Each policy emails the team. The three log events are JSON log lines with severity ERROR; Cloud
# Run (dbt, loader) and Workflows (watchdog) both send them to Cloud Logging as jsonPayload.

locals {
  has_email = var.alert_email != ""
  channels  = local.has_email ? [google_monitoring_notification_channel.team[0].id] : []

  # name => what the event means. The metric counts log lines whose jsonPayload.event matches.
  log_events = {
    freshness_breach  = "An entity is older than its freshness promise (freshness_check)."
    watchdog_stale    = "The simulator heartbeat or the case events have stopped (poc-watchdog)."
    crm_guard_tripped = "A CRM export changed too many accounts and was held (poc-crm-loader)."
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
  }
}

# ---- 1. a poc-* workflow failed -------------------------------------------------------------------

resource "google_monitoring_alert_policy" "workflow_failed" {
  project      = var.project_id
  display_name = "POC: a poc-* workflow execution failed"
  combiner     = "OR"
  severity     = "ERROR"

  documentation {
    mime_type = "text/markdown"
    content   = "A Cloud Workflows execution of a `poc-*` workflow finished as FAILED. Open the execution in Workflows to see the step and the error; the micro-batch also logs each step to `ops_<env>.pipeline_run_steps`."
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
      doc   = "`freshness_check` found an entity older than its promise. The log line names the entity, its age and its promise. See `ops_<env>.freshness_result`. Owners are in the `entity_registry` seed."
    }
    watchdog_stale = {
      title = "POC: the source side has stopped"
      doc   = "`poc-watchdog` found no recent simulator heartbeat or case event. Check the simulator job, the Datastream stream and Cloud SQL, in that order. Night-off pauses the watchdog, so this is not a night-time false alarm."
    }
    crm_guard_tripped = {
      title = "POC: a CRM export was held"
      doc   = "The CRM loader held an export because too many accounts changed (DQ42). Review it, then release it with `poc-crm-loader --approve export_ts=<timestamp>`."
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
