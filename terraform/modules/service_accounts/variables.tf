variable "project_id" {
  description = "Sandbox project. dev and int share it (D-22)."
  type        = string
}

variable "scope" {
  description = <<-EOT
    Which half of section 4.4 this call creates:
      shared - once per project, from terraform/shared: the shared service accounts, reader job user,
               the writer's custom role, and who may impersonate whom.
      env    - once per environment, from terraform/env: sa-dwh-writer-<env> and every dataset grant
               of that environment.
  EOT
  type        = string

  validation {
    condition     = contains(["shared", "env"], var.scope)
    error_message = "scope must be shared or env."
  }
}

# ------------------------------------------------------------------------------------- shared scope
variable "skip_service_accounts" {
  description = <<-EOT
    Shared service accounts that already exist (created by hand before D2, e.g. sa-orchestrator) and
    must not be created here. Their grants still apply. Better: terraform import them, then empty this.
  EOT
  type        = set(string)
  default     = []
}

variable "security_test_runners" {
  description = <<-EOT
    Members that run the security suite (D5) and the access-removal test (D6), e.g. "user:a@b.com" or
    the CI account. They get token creator on the test readers, sa-app-tenant-* and sa-pii-probe only,
    never on a writer (AT-27).
  EOT
  type        = list(string)
  default     = []
}

variable "human_readers" {
  description = <<-EOT
    People who read wh_<env> with their own Google account: the internal analyst and the two Looker
    Studio users (D10), e.g. "user:a@b.com". Shared scope gives them job user at project level only;
    env scope gives them viewer on wh_<env>. Remove the Looker users after the D10 check.
  EOT
  type        = list(string)
  default     = []
}

variable "crm_landing_dataset" {
  description = "raw_crm (B3). Empty until the crm_landing module creates it; then sa-crm-loader gets editor on it."
  type        = string
  default     = ""
}

variable "sim_dataset" {
  description = "sim_g2_datalake (A6). Empty until it exists; then sa-simulator gets editor on it."
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------------------- env scope
variable "env" {
  description = "dev or int. Required when scope = env."
  type        = string
  default     = ""
}

variable "writer_read_datasets" {
  description = <<-EOT
    Shared datasets sa-dwh-writer-<env> reads (section 4.4): raw_*, sim_g2_datalake, keys. A dataset
    that does not exist yet fails the apply: leave it out in <env>.tfvars until its owner creates it.
  EOT
  type        = list(string)
  default     = ["raw_g2", "raw_lpos", "raw_crm", "sim_g2_datalake", "keys"]
}

variable "writer_env_layers" {
  description = <<-EOT
    Per-environment layers sa-dwh-writer-<env> writes, as <layer>_<env> (section 4.2). They come from
    the bq_env module (Dev 4) and must exist first. wh is handled separately (custom role, readers).
  EOT
  type        = list(string)
  default     = ["stg", "prep", "build", "sec", "dq", "ops"]
}

variable "writer_rls_role_scope" {
  description = <<-EOT
    Where pocDwhWriterRls is granted to the writer: "dataset" (wh_<env> only, least privilege) or
    "project". Spike 2 records whether a dataset-level grant is enough; switch to "project" if not.
  EOT
  type        = string
  default     = "dataset"

  validation {
    condition     = contains(["dataset", "project"], var.writer_rls_role_scope)
    error_message = "writer_rls_role_scope must be dataset or project."
  }
}

variable "wh_exists" {
  description = "wh_<env> exists (bq_env, Dev 4). False skips every wh grant so the writer can be created first."
  type        = bool
  default     = true
}
