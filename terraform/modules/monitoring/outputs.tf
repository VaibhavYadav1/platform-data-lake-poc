output "notification_channel_id" {
  description = "Email channel of the team, or null while alert_email is empty."
  value       = local.has_email ? google_monitoring_notification_channel.team[0].id : null
}

output "alert_policy_ids" {
  description = "Resource ids of the four alert policies."
  value = concat(
    [google_monitoring_alert_policy.workflow_failed.id],
    [for p in google_monitoring_alert_policy.event : p.id],
  )
}
