variable "project_id" { type = string }
variable "region" { type = string }

variable "pg_public_ip" {
  description = "poc-ops-db public IP (cloudsql_g2 output)."
  type        = string
}

variable "pg_server_ca_cert" {
  description = "poc-ops-db server CA, PEM (cloudsql_g2 output)."
  type        = string
}

variable "raw_dataset_id" {
  description = "BigQuery dataset the stream writes to (created in terraform/shared)."
  type        = string
  default     = "raw_g2"
}