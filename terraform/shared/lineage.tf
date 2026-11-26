# E10: Data Lineage API and the dbt docs bucket.
#
# With the Data Lineage API on, BigQuery jobs record lineage between tables on their own: no
# change in dbt or publish.py. The console then shows raw_g2 -> build_<env> -> wh_<env>
# (between tables, not columns).
#
# The docs bucket holds one static HTML page per environment, written by cloudbuild/main.yaml
# after each deploy: gs://<project>-dbt-docs/<env>/index.html (plus manifest.json beside it, which
# the AT-37 check reads to confirm every model has a description).

resource "google_project_service" "datalineage" {
  project = var.project_id
  service = "datalineage.googleapis.com"

  disable_on_destroy = false
}

variable "docs_extra_readers" {
  description = "Extra members (user:, group:, serviceAccount:) that may open the dbt docs. Anyone with the Viewer role on the project can already open them, so this is usually empty."
  type        = list(string)
  default     = []
}

resource "google_storage_bucket" "dbt_docs" {
  project  = var.project_id
  name     = "${var.project_id}-dbt-docs"
  location = var.region

  uniform_bucket_level_access = true
  # No public or allAuthenticatedUsers grant can ever be added to this bucket.
  public_access_prevention = "enforced"

  # The pages are rebuilt on every merge, so there is nothing to keep: destroy can empty it.
  force_destroy = true

  labels = {
    poc = "phase2"
  }
}

# The deploy build (cloudbuild/main.yaml) runs as sa-cloudbuild-deploy and writes the pages.
resource "google_storage_bucket_iam_member" "docs_writer" {
  bucket = google_storage_bucket.dbt_docs.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.cloudbuild_deploy.email}"
}

resource "google_storage_bucket_iam_member" "docs_extra_readers" {
  for_each = toset(var.docs_extra_readers)

  bucket = google_storage_bucket.dbt_docs.name
  role   = "roles/storage.objectViewer"
  member = each.value
}
