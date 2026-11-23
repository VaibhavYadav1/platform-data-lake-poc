project_id = "gks-datalake-poc2-dev"
region     = "us-central1"
env        = "dev"

# E4: micro-batch every 15 minutes, with the CRM loader (int: hourly, no loader)
micro_batch_schedule = "*/15 * * * *"
run_crm_loader       = true
