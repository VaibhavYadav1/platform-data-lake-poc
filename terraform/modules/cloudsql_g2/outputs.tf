output "instance_name" {
  value = google_sql_database_instance.g2.name
}

output "connection_name" {
  description = "project:region:instance, for the Auth Proxy and the simulator (PG_INSTANCE)."
  value       = google_sql_database_instance.g2.connection_name
}

output "public_ip" {
  description = "Datastream's connection profile connects here (A4)."
  value       = google_sql_database_instance.g2.public_ip_address
}

output "secret_ids" {
  description = "Secret Manager ids of the three passwords (names only, never values)."
  value       = { for k, s in google_secret_manager_secret.db : k => s.secret_id }
}
