# Everyone runs the same Terraform major/minor line (install: `winget install Hashicorp.Terraform`).
# Provider versions are pinned here, once for every module this root calls (random: A1 passwords).
terraform {
  required_version = "~> 1.17"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.12"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Settings come from backend.hcl: terraform init -backend-config=backend.hcl
  backend "gcs" {}
}
