output "topic_id" {
  description = "Full topic id for the publisher (CASE_TOPIC, A7/A8)."
  value       = google_pubsub_topic.case_events.id
}
