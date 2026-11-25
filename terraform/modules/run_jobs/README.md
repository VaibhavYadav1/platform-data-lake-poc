# terraform/modules/run_jobs

**Owner:** Dev 4  
**Tasks:** E3

Cloud Run jobs per environment: `poc-dbt-runner-{env}`, `poc-crm-loader`.

`poc-source-simulator` (A8) is not here: there is one simulator for the whole sandbox, so it lives in
`terraform/shared/simulator.tf` with its scheduler `poc-simulator-tick` and service account `sa-simulator`.

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".
