project_id = "gks-datalake-poc2-dev"
region     = "us-central1"

# A8: simulator image
simulator_image = "us-central1-docker.pkg.dev/gks-datalake-poc2-dev/poc/poc-source-simulator:b2ec315"

# B2: the simulator writes the hourly CRM export here (bucket created in crm_exports.tf)
simulator_crm_bucket = "gks-datalake-poc2-dev-crm-exports"
