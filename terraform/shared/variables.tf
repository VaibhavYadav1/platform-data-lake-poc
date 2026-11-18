variable "project_id" {
  description = "GCP project that holds the shared resources."
  type        = string
}

variable "region" {
  description = "Default region for regional resources."
  type        = string
  default     = "us-central1"
}
