output "emails" {
  description = "Shared service account emails by name (fixed by convention; valid in both scopes)."
  value       = local.email
}

output "writer_email" {
  description = "sa-dwh-writer-<env>. Empty in the shared scope."
  value       = local.is_env ? google_service_account.writer[0].email : ""
}

output "writer_rls_role" {
  description = "Full name of the custom role pocDwhWriterRls. Empty in the env scope."
  value       = local.shared ? google_project_iam_custom_role.writer_rls[0].name : ""
}

output "tenant_principals" {
  description = "What config.<env>.yaml tenant_principals needs (D4): every tenant reader, as policy grantees."
  value = [for a in ["sa-tenant-a-user", "sa-tenant-b-user", "sa-app-tenant-a", "sa-app-tenant-b"] :
  "serviceAccount:${local.email[a]}"]
}
