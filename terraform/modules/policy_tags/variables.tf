variable "project_id" {
  description = "Sandbox project."
  type        = string
}

variable "region" {
  description = "Taxonomy location; must match the tagged datasets (D-21)."
  type        = string
  default     = "us-central1"
}

variable "fine_grained_readers" {
  description = <<-EOT
    Members that see the real values of tagged columns: both writers (they tokenise) and one internal
    person for the test. Add sa-crm-loader or the Datastream agent here only if D9 step 4 shows
    tagging broke their writes.
  EOT
  type        = list(string)
}

variable "enable_pii_indirect" {
  description = "Also create pii_indirect for user ids (pii-inventory.md section 5, decision 1). Off until decided."
  type        = bool
  default     = false
}

variable "enable_masking" {
  description = "Create a SHA-256 masking policy on pii_direct. Turn on only if spike 3 says masking is available."
  type        = bool
  default     = false
}

variable "masked_readers" {
  description = "Members that see SHA-256 hashes instead of values when masking is on: the internal analyst and sa-pii-probe."
  type        = list(string)
  default     = []
}
