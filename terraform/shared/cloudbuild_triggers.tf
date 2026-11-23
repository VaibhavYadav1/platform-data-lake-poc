# E1: run cloudbuild/pr.yaml on pull requests to main, and only on pull requests.
# There is deliberately no push trigger here. Merges are handled by main.yaml (E2).
#
# One-time, by hand: install the Cloud Build GitHub app on the repository (see the runbook).
# This trigger's name is the check name GitHub shows, so it is the one to mark as required
# in branch protection.

variable "github_owner" {
  description = "GitHub user or organisation that owns the repository."
  type        = string
  default     = "VaibhavYadav1"
}

variable "github_repo" {
  description = "GitHub repository name."
  type        = string
  default     = "platform-data-lake-poc"
}

variable "cloudbuild_triggers_disabled" {
  description = "Disable both Cloud Build triggers (poc-pr-checks and poc-main-deploy). True: neither pull requests nor merges start a build. Set to false to turn CI and CD back on."
  type        = bool
  default     = true
}

resource "google_cloudbuild_trigger" "pr_checks" {
  disabled = var.cloudbuild_triggers_disabled

  project     = var.project_id
  name        = "poc-pr-checks"
  description = "E1: Terraform, pytest, rule checks and dbt CI on every pull request to main"
  filename    = "cloudbuild/pr.yaml"

  service_account = google_service_account.cloudbuild.id
  depends_on      = [google_project_iam_member.cloudbuild]

  github {
    owner = var.github_owner
    name  = var.github_repo

    pull_request {
      branch          = "^main$"
      comment_control = "COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY"
    }
  }

  # _PR_NUMBER is filled in by Cloud Build for pull request triggers.
}
