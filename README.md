# platform-data-lake-poc

POC 2 (Phase 2) of the Store Alert Data Lake: a centralized, read-only BigQuery data warehouse.
The plan is `GKS-POC-Phase2-detailed-plan.md`. Every folder has a `README.md` with its owner, its tasks and the
files that go there.

- **Dev project:** `gks-datalake-poc2-dev` ("GKS Data Lake POC2 - Dev"), region `us-central1`. Generated data only.
  Terraform state: `gs://gks-datalake-poc2-dev-tfstate` (versioned), one prefix per root module (`shared`, `env/dev`).
  `int` will get its own project, `gks-datalake-poc2-int`.
- **Phase 1 sandbox:** `data-lake-poc-512405` stays as it is. POC 2 does not deploy there.
- **Setup:** Terraform `~> 1.17` (`winget install Hashicorp.Terraform`), the gcloud CLI (`winget install Google.CloudSDK`),
  then `gcloud auth login`, `gcloud auth application-default login` and
  `gcloud config set project gks-datalake-poc2-dev`.
- **Environments:** `dev` and `int`, from the same Terraform and dbt code.
- **Simulator:** lives here, in `simulator/`. The Phase 1 repos (`data-gen-upload-data-lake-poc` and the rest) are
  read-only: Phase 2 changes nothing there.

## Layout and owners

| Folder | What | Owner |
| --- | --- | --- |
| `terraform/shared` | Shared resources: sources, landing, policy tags, audit sink, reservations | Dev 4 (Dev 2 reviews every plan) |
| `terraform/env` | One root module for `dev` and `int` | Dev 4 |
| `terraform/modules/cloudsql_g2`, `datastream_pg`, `service_accounts`, `audit_sink` | Cloud SQL, CDC, identities, audit | Dev 2 |
| `terraform/modules/pubsub_bq`, `bq_env`, `run_jobs`, `workflows`, `monitoring` | Case events, datasets, jobs, orchestration, alerts | Dev 4 |
| `terraform/modules/crm_landing` | CRM bucket, `raw_crm`, loader job | Dev 3 |
| `terraform/modules/sim_g2_datalake`, `reservations` | `sim_g2_datalake`, BI Engine and slots | Dev 1 |
| `terraform/modules/policy_tags` | Personal-data taxonomy | Dev 5 |
| `dbt/` (framework) | Project config, conventions, tests framework | Dev 1 |
| `dbt/models/staging/g2`, `staging/crm`, `intermediate/crm` | CDC staging, CRM replica | Dev 3 |
| `dbt/models/marts/core`, `marts/wheel`, `rollups` | Alert dims and facts, wheel tables, marts | Dev 1 (Dev 3: incremental facts) |
| `dbt/models/marts/crm`, `marts/calendar`, `intermediate/tenant` | Customer, tenant, `dim_date` | Dev 5 (Dev 3: `fct_work_order`) |
| `dbt/models/staging/lpos`, `marts/lpos` | Case events | Dev 4 |
| `dbt/models/security` | `map_tenant_access` | Dev 2 |
| `orchestration/` | Workflows, `publish.py` | Dev 4 (Dev 2: night-off, morning-on) |
| `orchestration/publish/policies` | Row access policies | Dev 2 |
| `orchestration/publish/objects` | Native materialized views | Dev 1 |
| `simulator/` | `poc-source-simulator`: G2, case events, CRM exports, `sim_g2_datalake` | Dev 3 |
| `loaders/crm` | `poc-crm-loader` | Dev 3 |
| `apps/tenant_reader` | Per-tenant test application | Dev 2 |
| `sql/g2` | G2 schema and replication | Dev 3 (schema), Dev 2 (replication) |
| `scripts/` | Acceptance, parity, security, scale, benchmark, CI checks | Per subfolder README |
| `cloudbuild/` | CI on pull requests, CD on merge | Dev 4 |
| `docs/poc2/` | Baseline, specs, spikes, reports, runbook | Per file |

Each folder's `README.md` names its owner. Ask that owner to review any pull request that touches the folder.

## Working in parallel

1. **One branch and one pull request per task:** `p2/<task-id>-<short-name>`, for example `p2/E5-publish`. The
   title starts with the task ID.
2. **Stay in your folders.** If you must change someone else's folder, keep it a separate small pull request and
   let them review it.
3. **dbt: one `.sql` and one `.yml` per model,** named after the model, and one `sources_<system>.yml` per source.
   No shared `schema.yml`: that is where merge conflicts come from.
4. **dbt on a laptop:** `--target local` builds into `dbt_<you>_*`. Never build into `build_dev` or `wh_dev`.
5. **Terraform:** each module is owned by one person. Root modules (`shared`, `env`) only wire modules together, so
   adding a module is a few lines there. Never change anything Terraform owns in the console.
6. **CI must pass,** and one reviewer from another POC approves.
7. **Secrets** live in Secret Manager. Never in code, `tfvars`, query text or logs.
8. **Labels** on every resource: `poc=phase2`, `env`, `owner=dev<n>`, `managed_by=terraform|dbt|publish`.

## Who unblocks whom (first days)

| Needed by | Comes from | Owner | Day |
| --- | --- | --- | --- |
| Everyone using Terraform | `terraform/shared`, `terraform/env` skeleton (0.2) | Dev 4 | 1–2 |
| Everyone using dbt | `dbt/` skeleton (0.4) | Dev 1 | 1–2 |
| Simulator, Cloud SQL | `sql/g2/schema.sql` (0.5) | Dev 3 | 1 |
| Everyone | `docs/poc2/specs.md` (0.7) | Dev 5 | 1–2 |
| publish design, security | `docs/poc2/spikes.md` (0.9) | Dev 2, Dev 1, Dev 4 | 2 |
