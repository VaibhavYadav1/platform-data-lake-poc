variable "project_id" {
  description = "GCP project for this environment, e.g. gks-datalake-poc2-dev."
  type        = string
}

variable "region" {
  description = "Default region for regional resources."
  type        = string
  default     = "us-central1"
}

variable "env" {
  description = "Environment name: dev or int. Used in dataset names and the env label."
  type        = string

  validation {
    condition     = contains(["dev", "int"], var.env)
    error_message = "env must be dev or int."
  }
}
