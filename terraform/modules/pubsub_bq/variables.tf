variable "project_id" {
  type = string
}

variable "case_event_avsc_path" {
  description = "Path to terraform/shared/schemas/case_event.avsc."
  type        = string
}

variable "raw_dataset_id" {
  description = "Dataset for case_event (created in terraform/shared)."
  type        = string
  default     = "raw_lpos"
}
