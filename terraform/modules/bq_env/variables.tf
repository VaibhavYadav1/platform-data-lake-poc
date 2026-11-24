variable "project_id" {
  description = "GCP project that holds the datasets."
  type        = string
}

variable "env" {
  description = "Environment name: dev or int."
  type        = string
}

variable "region" {
  description = "BigQuery location for all datasets."
  type        = string
  default     = "us-central1"
}
