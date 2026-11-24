# The ops_{env} dataset for this environment.
#
# Only the dataset: the workflows, publish.py, full_load.py and the freshness macro each create
# their own ops tables on their first run, but none of them can create the dataset itself.

module "bq_env" {
  source = "../modules/bq_env"

  project_id = var.project_id
  env        = var.env
  region     = var.region
}
