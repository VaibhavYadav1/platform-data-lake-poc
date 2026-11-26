# POC D, per-environment half (D2): sa-dwh-writer-<env> and every dataset grant of this environment.
# Needs: terraform/shared applied (custom role pocDwhWriterRls, reader service accounts), and the
# datasets of bq_env (Dev 4). A grant on a dataset that does not exist fails the apply: list only the
# existing ones in <env>.tfvars, and set wh_exists = false until wh_<env> exists.

variable "writer_read_datasets" {
  description = "Shared datasets the writer reads: raw_*, sim_g2_datalake, keys (section 4.4). Only those that exist."
  type        = list(string)
  default     = ["raw_g2", "raw_lpos", "raw_crm", "sim_g2_datalake", "keys"]
}

variable "writer_env_layers" {
  description = "Layers the writer edits, as <layer>_<env>. Created by bq_env."
  type        = list(string)
  default     = ["stg", "prep", "build", "sec", "dq", "ops"]
}

variable "wh_exists" {
  description = "wh_<env> exists. False skips the wh grants."
  type        = bool
  default     = true
}

variable "human_readers" {
  description = "Internal analyst and Looker Studio users: viewer on wh_<env>. Same list as terraform/shared."
  type        = list(string)
  default     = []
}

variable "writer_rls_role_scope" {
  description = "Grant pocDwhWriterRls on wh_<env> (\"dataset\") or the project (\"project\"), per spike 2."
  type        = string
  default     = "project" # proven by spike 2; a dataset-level grant was not tested
}

module "security" {
  source = "../modules/service_accounts"

  project_id            = var.project_id
  scope                 = "env"
  env                   = var.env
  writer_read_datasets  = var.writer_read_datasets
  writer_env_layers     = var.writer_env_layers
  wh_exists             = var.wh_exists
  human_readers         = var.human_readers
  writer_rls_role_scope = var.writer_rls_role_scope
}

output "writer_email" {
  value = module.security.writer_email
}
