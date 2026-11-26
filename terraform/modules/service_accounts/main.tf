# D2: the identities and IAM of plan section 4.4, with the changes in the POC D design
# (docs/poc2/poc-d-security-design.md, section 4):
#   - sa-pii-probe: reads raw_crm without the personal-data tag, so D5 case 5 tests the tag;
#   - pocDwhWriterRls adds rowAccessPolicies.get and drops tables.setCategory;
#   - the security-suite runner may impersonate the test readers, never a writer.
#
# Two halves of one module, so every grant of section 4.4 lives in one place:
#   scope = "shared"  once per project (terraform/shared)
#   scope = "env"     once per environment (terraform/env), for dev and int
#
# Readers get no project-level BigQuery data role anywhere: only job user at project level and viewer
# on wh_<env>. Nothing here gives anyone token creator or service account user on a writer (AT-27).

locals {
  shared = var.scope == "shared"
  is_env = var.scope == "env"

  sa_domain = "${var.project_id}.iam.gserviceaccount.com"

  # name => display name. The emails are fixed by convention, so the env half and other roots can name
  # them without reading this root's state.
  shared_accounts = {
    "sa-simulator"     = "Source simulator (A2, A7)"
    "sa-crm-loader"    = "CRM loader (B3)"
    "sa-orchestrator"  = "Workflows and Cloud Scheduler (E4, E8)"
    "sa-tenant-a-user" = "Tenant A staff, for the security tests (D5)"
    "sa-tenant-b-user" = "Tenant B staff, for the security tests (D5)"
    "sa-test-app"      = "Test application (D7); impersonates sa-app-tenant-a/b only"
    "sa-app-tenant-a"  = "Test application acting for tenant A (D7)"
    "sa-app-tenant-b"  = "Test application acting for tenant B (D7)"
    "sa-pii-probe"     = "Reads raw_crm without the personal-data tag (D5 case 5, AT-28)"
  }
  created_accounts = local.shared ? {
    for name, title in local.shared_accounts : name => title if !contains(var.skip_service_accounts, name)
  } : {}

  email = { for name in keys(local.shared_accounts) : name => "${name}@${local.sa_domain}" }

  # Identities that read wh_<env> as a tenant or for tests. Each gets job user (shared) and viewer on
  # wh_<env> (env), nothing else.
  reader_accounts = ["sa-tenant-a-user", "sa-tenant-b-user", "sa-app-tenant-a", "sa-app-tenant-b"]

  # Who the security-suite runner may impersonate: every test reader, never a writer.
  impersonable_by_runner = concat(local.reader_accounts, ["sa-pii-probe"])

  writer_rls_permissions = [
    "bigquery.rowAccessPolicies.create",
    "bigquery.rowAccessPolicies.update",
    "bigquery.rowAccessPolicies.delete",
    "bigquery.rowAccessPolicies.list",
    "bigquery.rowAccessPolicies.get",
    "bigquery.rowAccessPolicies.getIamPolicy",
    "bigquery.rowAccessPolicies.setIamPolicy",
  ]
}

# =================================================================================== shared scope
resource "google_service_account" "shared" {
  for_each     = local.created_accounts
  project      = var.project_id
  account_id   = each.key
  display_name = each.value
}

# Project-level roles. Readers: job user only. The pipeline accounts: what their jobs need that is
# not tied to a resource another POC creates (bucket, topic and dataset grants sit with those).
resource "google_project_iam_member" "shared" {
  for_each = local.shared ? merge(
    { for a in concat(local.reader_accounts, ["sa-pii-probe"]) : "${a}/jobUser" => {
    member = "serviceAccount:${local.email[a]}", role = "roles/bigquery.jobUser" } },
    { for m in var.human_readers : "${m}/jobUser" => { member = m, role = "roles/bigquery.jobUser" } },
    {
      "sa-crm-loader/jobUser"     = { member = "serviceAccount:${local.email["sa-crm-loader"]}", role = "roles/bigquery.jobUser" }
      "sa-simulator/cloudsql"     = { member = "serviceAccount:${local.email["sa-simulator"]}", role = "roles/cloudsql.client" }
      "sa-orchestrator/run"       = { member = "serviceAccount:${local.email["sa-orchestrator"]}", role = "roles/run.invoker" }
      "sa-orchestrator/workflows" = { member = "serviceAccount:${local.email["sa-orchestrator"]}", role = "roles/workflows.invoker" }
      "sa-orchestrator/jobUser"   = { member = "serviceAccount:${local.email["sa-orchestrator"]}", role = "roles/bigquery.jobUser" } # watchdog query (design 4.3)
      "sa-orchestrator/logWriter" = { member = "serviceAccount:${local.email["sa-orchestrator"]}", role = "roles/logging.logWriter" }
      "sa-simulator/logWriter"    = { member = "serviceAccount:${local.email["sa-simulator"]}", role = "roles/logging.logWriter" }
      "sa-crm-loader/logWriter"   = { member = "serviceAccount:${local.email["sa-crm-loader"]}", role = "roles/logging.logWriter" }
    },
  ) : {}

  project    = var.project_id
  role       = each.value.role
  member     = each.value.member
  depends_on = [google_service_account.shared]
}

# The writer's custom role: manage row access policies on wh_<env> (D4, E5). Once per project; the
# env half binds it. Spike 2 step s2d confirms this list; update it here if the spike needs more.
resource "google_project_iam_custom_role" "writer_rls" {
  count       = local.shared ? 1 : 0
  project     = var.project_id
  role_id     = "pocDwhWriterRls"
  title       = "POC dwh writer: row access policies"
  description = "Lets sa-dwh-writer-<env> create, replace and list row access policies (D2, D4)."
  permissions = local.writer_rls_permissions
}

# sa-test-app may impersonate the two app identities and nothing else (D7).
resource "google_service_account_iam_member" "test_app" {
  for_each           = local.shared ? toset(["sa-app-tenant-a", "sa-app-tenant-b"]) : toset([])
  service_account_id = "projects/${var.project_id}/serviceAccounts/${local.email[each.key]}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${local.email["sa-test-app"]}"
  depends_on         = [google_service_account.shared]
}

# The security-suite runner (a developer or CI) impersonates each test identity (D5, D6).
resource "google_service_account_iam_member" "runner" {
  for_each = local.shared ? {
    for pair in setproduct(local.impersonable_by_runner, var.security_test_runners) : "${pair[0]}/${pair[1]}" => {
      account = pair[0], member = pair[1]
    }
  } : {}
  service_account_id = "projects/${var.project_id}/serviceAccounts/${local.email[each.value.account]}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = each.value.member
  depends_on         = [google_service_account.shared]
}

# Shared landing datasets, once their owners have created them.
resource "google_bigquery_dataset_iam_member" "crm_loader" {
  count      = local.shared && var.crm_landing_dataset != "" ? 1 : 0
  project    = var.project_id
  dataset_id = var.crm_landing_dataset
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${local.email["sa-crm-loader"]}"
  depends_on = [google_service_account.shared]
}

# sa-pii-probe must be able to read raw_crm itself, so that D5 case 5 is stopped by the policy tag on the
# contact columns and not by dataset access; otherwise the test passes without testing the tag (design issue #1).
resource "google_bigquery_dataset_iam_member" "pii_probe" {
  count      = local.shared && var.crm_landing_dataset != "" ? 1 : 0
  project    = var.project_id
  dataset_id = var.crm_landing_dataset
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${local.email["sa-pii-probe"]}"
  depends_on = [google_service_account.shared]
}

resource "google_bigquery_dataset_iam_member" "simulator" {
  count      = local.shared && var.sim_dataset != "" ? 1 : 0
  project    = var.project_id
  dataset_id = var.sim_dataset
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${local.email["sa-simulator"]}"
  depends_on = [google_service_account.shared]
}

# ====================================================================================== env scope
# The datasets below come from bq_env (Dev 4) and the shared roots. A grant on a dataset that does not
# exist fails the apply, so apply after them, or leave the missing ones out in <env>.tfvars.
locals {
  writer_email  = local.is_env ? "sa-dwh-writer-${var.env}@${local.sa_domain}" : ""
  writer_member = "serviceAccount:${local.writer_email}"
  wh            = "wh_${var.env}"
}

resource "google_service_account" "writer" {
  count        = local.is_env ? 1 : 0
  project      = var.project_id
  account_id   = "sa-dwh-writer-${var.env}"
  display_name = "dbt runner and publish.py, ${var.env} (C, E5)"
}

resource "google_project_iam_member" "writer_job_user" {
  count   = local.is_env ? 1 : 0
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.writer[0].email}"
}

resource "google_bigquery_dataset_iam_member" "writer_read" {
  for_each   = local.is_env ? toset(var.writer_read_datasets) : toset([])
  project    = var.project_id
  dataset_id = each.value
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.writer[0].email}"
}

resource "google_bigquery_dataset_iam_member" "writer_write" {
  for_each = local.is_env ? toset(concat(
    [for l in var.writer_env_layers : "${l}_${var.env}"],
    var.wh_exists ? [local.wh] : [],
  )) : toset([])
  project    = var.project_id
  dataset_id = each.value
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.writer[0].email}"
}

# sa-orchestrator writes the run log and freshness results in ops_<env> (plan section 4.4).
resource "google_bigquery_dataset_iam_member" "orchestrator_ops" {
  count      = local.is_env && contains(var.writer_env_layers, "ops") ? 1 : 0
  project    = var.project_id
  dataset_id = "ops_${var.env}"
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${local.email["sa-orchestrator"]}"
}

# pocDwhWriterRls is created by the shared scope; apply terraform/shared first.
resource "google_bigquery_dataset_iam_member" "writer_rls" {
  count      = local.is_env && var.wh_exists && var.writer_rls_role_scope == "dataset" ? 1 : 0
  project    = var.project_id
  dataset_id = local.wh
  role       = "projects/${var.project_id}/roles/pocDwhWriterRls"
  member     = "serviceAccount:${google_service_account.writer[0].email}"
}

resource "google_project_iam_member" "writer_rls" {
  count   = local.is_env && var.writer_rls_role_scope == "project" ? 1 : 0
  project = var.project_id
  role    = "projects/${var.project_id}/roles/pocDwhWriterRls"
  member  = "serviceAccount:${google_service_account.writer[0].email}"
}

# Readers: viewer on wh_<env> only. Rows are limited by the row access policies (D4); a reader named
# in no policy sees zero rows, so every reader here must also be in config.<env>.yaml.
# Spike 1: the tenant row policy reads sec_<env>.map_tenant_access as the reader, so readers need viewer on
# sec_<env> too. The table holds only hashed principals and tenant ids (docs/poc2/spikes.md).
resource "google_bigquery_dataset_iam_member" "sec_reader" {
  for_each = local.is_env && var.wh_exists && contains(var.writer_env_layers, "sec") ? toset(concat(
    [for a in local.reader_accounts : "serviceAccount:${local.email[a]}"],
    var.human_readers,
  )) : toset([])
  project    = var.project_id
  dataset_id = "sec_${var.env}"
  role       = "roles/bigquery.dataViewer"
  member     = each.value
}

resource "google_bigquery_dataset_iam_member" "wh_reader" {
  for_each = local.is_env && var.wh_exists ? toset(concat(
    [for a in local.reader_accounts : "serviceAccount:${local.email[a]}"],
    var.human_readers,
  )) : toset([])
  project    = var.project_id
  dataset_id = local.wh
  role       = "roles/bigquery.dataViewer"
  member     = each.value
}
