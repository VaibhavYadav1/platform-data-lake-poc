# Everyone runs the same Terraform major/minor line (install: `winget install Hashicorp.Terraform`).
# Provider pins (google, google-beta) are added here with the rest of the 0.2 skeleton.
terraform {
  required_version = "~> 1.17"

  # Settings come from backend.hcl: terraform init -backend-config=backend.hcl
  backend "gcs" {}
}
