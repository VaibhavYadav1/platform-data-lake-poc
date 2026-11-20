# E2: deploy on merge to main. Image repository, the account CD runs as, and the push trigger.
#
# The deploy account can change infrastructure, unlike sa-cloudbuild (plan only). Anything that
# merges to main runs as it, so keep the PR rules strict. Sandbox project only (D-22).

resource "google_artifact_registry_repository" "poc" {
  project       = var.project_id
  location      = var.region
  repository_id = "poc"
  format        = "DOCKER"
  description   = "dbt runner and CRM loader images, tagged with the commit SHA"

  labels = {
    poc = "phase2"
  }
}

resource "google_service_account" "cloudbuild_deploy" {
  project      = var.project_id
  account_id   = "sa-cloudbuild-deploy"
  display_name = "Cloud Build CD (terraform apply, image push)"
}

resource "google_project_iam_member" "cloudbuild_deploy" {
  for_each = toset([
    "roles/logging.logWriter",
    "roles/editor",                          # create and change the sandbox's resources
    "roles/resourcemanager.projectIamAdmin", # grant roles to the service accounts it creates
    "roles/iam.serviceAccountAdmin",         # create service accounts
    "roles/iam.serviceAccountUser",          # attach them to Cloud Run jobs and workflows
    "roles/artifactregistry.writer",         # push images
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.cloudbuild_deploy.email}"
}

resource "google_storage_bucket_iam_member" "cloudbuild_deploy_state" {
  bucket = var.tfstate_bucket
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.cloudbuild_deploy.email}"
}

resource "google_cloudbuild_trigger" "main_deploy" {
  project     = var.project_id
  name        = "poc-main-deploy"
  description = "E2: build images and terraform apply (shared, dev, int) on every merge to main"
  filename    = "cloudbuild/main.yaml"

  service_account = google_service_account.cloudbuild_deploy.id
  depends_on      = [google_project_iam_member.cloudbuild_deploy]

  github {
    owner = var.github_owner
    name  = var.github_repo

    push {
      branch = "^main$"
    }
  }
}
