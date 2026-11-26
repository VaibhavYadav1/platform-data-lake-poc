output "taxonomy_id" {
  value = google_data_catalog_taxonomy.pii.id
}

output "pii_direct_id" {
  description = "Full policy tag name; use it in a column's policyTags (crm_landing schema, tag_raw_columns.py)."
  value       = google_data_catalog_policy_tag.pii_direct.name
}

output "pii_indirect_id" {
  description = "Empty unless enable_pii_indirect."
  value       = var.enable_pii_indirect ? google_data_catalog_policy_tag.pii_indirect[0].name : ""
}
