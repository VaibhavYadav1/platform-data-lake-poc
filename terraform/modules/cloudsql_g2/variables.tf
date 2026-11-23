variable "project_id" {
  description = "GCP project for the instance and its secrets."
  type        = string
}

variable "region" {
  description = "Region of the instance. Must match the Datastream region (A4)."
  type        = string
}

variable "tier" {
  description = "Machine size. db-g1-small if db-f1-micro struggles."
  type        = string
  default     = "db-f1-micro"
}
