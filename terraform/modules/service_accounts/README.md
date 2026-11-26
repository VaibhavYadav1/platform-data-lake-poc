# terraform/modules/service_accounts

**Owner:** Dev 2  
**Tasks:** D2

Identities and IAM from plan section 4.4, including the writer's custom role.

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".

## What it creates

One module, two calls (`scope`):

| Scope | Called from | Creates |
|---|---|---|
| `shared` | `terraform/shared/security.tf` | `sa-simulator`, `sa-crm-loader`, `sa-orchestrator`, `sa-tenant-a-user`, `sa-tenant-b-user`, `sa-test-app`, `sa-app-tenant-a`, `sa-app-tenant-b`, `sa-pii-probe`; job user for readers (no project data roles); custom role `pocDwhWriterRls`; token creator for `sa-test-app` on `sa-app-tenant-a/b` only; token creator for `security_test_runners` on the test identities only (never a writer) |
| `env` | `terraform/env/security.tf` | `sa-dwh-writer-<env>`; viewer on the shared read datasets; editor on `stg/prep/build/sec/dq/ops_<env>` and `wh_<env>`; `pocDwhWriterRls` on `wh_<env>` (or the project, per spike 2); viewer on `wh_<env>` for the readers |

`pocDwhWriterRls` = `bigquery.rowAccessPolicies.create/update/delete/list/get/getIamPolicy/setIamPolicy`
(the POC D design adds `.get` and drops `tables.setCategory`). Spike 2 step `s2d` confirms the final list.

## Inputs worth knowing

- `skip_service_accounts`: accounts created by hand before D2 (e.g. `sa-orchestrator`). Prefer `terraform import`.
- `security_test_runners`, `human_readers` (analyst, Looker users): set in `terraform.tfvars` / `<env>.tfvars`.
- `writer_read_datasets`, `writer_env_layers`, `wh_exists`: list only datasets that exist; a grant on a missing dataset fails the apply.
- `crm_landing_dataset`, `sim_dataset`: empty until POC B / A create them.

## Apply order

1. `terraform/shared` with `writers_exist = false` (accounts, custom role, sink, tags).
2. `bq_env` datasets (Dev 4).
3. `terraform/env` with `<env>.tfvars` (creates `sa-dwh-writer-<env>`).
4. `terraform/shared` again with `writers_exist = true`: the writers get fine-grained reader on the tags.
5. Put the `tenant_principals` output into `orchestration/publish/config.<env>.yaml`.

Bucket, topic and Cloud SQL instance grants for the pipeline accounts stay with the modules that create those resources.
