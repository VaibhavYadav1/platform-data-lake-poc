# POC D, shared half: identities (D2), the audit sink (D8, created with D2) and the personal-data
# tags (D9). The per-environment half (sa-dwh-writer-<env>, dataset grants) is terraform/env/security.tf.
# Apply this root first: the env root binds the custom role pocDwhWriterRls created here.

variable "security_test_runners" {
  description = "Members that run the security suite (D5, D6), e.g. \"user:a@b.com\". Token creator on the test identities only."
  type        = list(string)
  default     = []
}

variable "human_readers" {
  description = "Internal analyst and the two Looker Studio users (D10), e.g. \"user:a@b.com\". Project job user only."
  type        = list(string)
  default     = []
}

variable "internal_pii_reader" {
  description = "One internal person who may see raw personal data for the D9 test, e.g. \"user:a@b.com\". Empty: none."
  type        = string
  default     = ""
}

variable "skip_service_accounts" {
  description = "Shared service accounts already created by hand (e.g. sa-orchestrator). Import them instead when possible."
  type        = set(string)
  default     = []
}

variable "writers_exist" {
  description = "sa-dwh-writer-dev/int exist (terraform/env applied). False on the first apply: IAM members naming a missing account fail."
  type        = bool
  default     = false
}

variable "crm_landing_dataset" {
  description = "raw_crm, once POC B's crm_landing module has created it: sa-crm-loader writes it, sa-pii-probe reads it (D5 case 5)."
  type        = string
  default     = ""
}

variable "enable_masking" {
  description = "Spike 3 said BigQuery data masking is available: create the SHA-256 policy on pii_direct."
  type        = bool
  default     = true # spike 3: masking works on our pricing
}

module "service_accounts" {
  source = "../modules/service_accounts"

  project_id            = var.project_id
  scope                 = "shared"
  skip_service_accounts = var.skip_service_accounts
  security_test_runners = var.security_test_runners
  human_readers         = var.human_readers
  sim_dataset           = ""
  crm_landing_dataset   = var.crm_landing_dataset
}

module "audit_sink" {
  source = "../modules/audit_sink"

  project_id = var.project_id
  region     = var.region
}

module "policy_tags" {
  source = "../modules/policy_tags"

  project_id = var.project_id
  region     = var.region
  fine_grained_readers = concat(
    var.writers_exist ? [for env in ["dev", "int"] : "serviceAccount:sa-dwh-writer-${env}@${var.project_id}.iam.gserviceaccount.com"] : [],
    var.internal_pii_reader != "" ? [var.internal_pii_reader] : [],
  )
  enable_masking = var.enable_masking
  masked_readers = concat(
    ["serviceAccount:${module.service_accounts.emails["sa-pii-probe"]}"],
    [for m in var.human_readers : m if m != var.internal_pii_reader],
  )
}

output "tenant_principals" {
  description = "Paste into orchestration/publish/config.<env>.yaml tenant_principals (plus the Looker users)."
  value       = module.service_accounts.tenant_principals
}

output "pii_direct_policy_tag" {
  description = "Policy tag for raw_crm contact columns (crm_landing schema) and tag_raw_columns.py."
  value       = module.policy_tags.pii_direct_id
}
