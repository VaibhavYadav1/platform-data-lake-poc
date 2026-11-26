# terraform/modules/audit_sink

**Owner:** Dev 2  
**Tasks:** D8

Log sink of BigQuery audit logs into `audit_logs`.

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".

## What it creates

- Dataset `audit_logs` (us-central1). Engineers only: entries contain callers' emails.
- Sink `poc-bq-audit`: `protoPayload.serviceName="bigquery.googleapis.com" OR "iamcredentials.googleapis.com"`,
  partitioned tables, unique writer identity with editor on `audit_logs`.
- Data access logs (ADMIN_READ, DATA_READ, DATA_WRITE) for `iamcredentials.googleapis.com`, so impersonation
  attempts (D5 case 4) are logged. BigQuery's are on by default.

Created with D2, not D8 (design issue #2), so the first D5 runs already leave evidence. The D8 evidence
queries live in `scripts/security/` and `docs/poc2/security-report.md`.

Called from `terraform/shared/security.tf`. Inputs: `project_id`, `region`, `dataset_id`, `sink_name`,
`enable_iamcredentials_data_access_logs`.
