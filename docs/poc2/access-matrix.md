# Identity and access matrix (plan section 4.4, prepares D2)

Owner: Dev 2. Reviewers: Dev 4 (Terraform, orchestration), Dev 5 (tenant rules, personal data).
Status: DRAFT. Rows marked **NEW** or **CHANGED** differ from plan section 4.4; section 6 explains each one.
Everything is in project `gks-datalake-poc2-dev` unless noted. `{env}` is `dev` or `int`.

## 1. Identities

| Identity | Kind | Stands for | Created by |
|---|---|---|---|
| `sa-simulator` | Service account | Source simulator job (and the `derived_alert` scheduled query, **NEW**) | Terraform `service_accounts` |
| `sa-crm-loader` | Service account | CRM loader job | Terraform |
| `sa-dwh-writer-{env}` | Service account | dbt runner and `publish.py` | Terraform |
| `sa-orchestrator` | Service account | Workflows and Cloud Scheduler | Terraform |
| `sa-tenant-a-user`, `sa-tenant-b-user` | Service account | Tenant staff (security tests) | Terraform |
| `sa-test-app` | Service account | Test application | Terraform |
| `sa-app-tenant-a`, `sa-app-tenant-b` | Service account | The application acting for one tenant | Terraform |
| `sa-pii-probe` **NEW** | Service account | A reader of raw tables without tag access (D5 case 5) | Terraform |
| Internal analyst | Named team member | Internal staff | Terraform IAM bindings |
| Looker user A, Looker user B | Two team members' Google accounts | Tenant staff in Looker Studio | Terraform IAM bindings, Day 11 only |
| Security-suite runner **NEW** | Dev 2's account and the CI build account | Runs D5, D6 and D7 by impersonation | Terraform IAM bindings |
| All-rows operators **NEW** | Whoever runs E11, F1 and F2 (Dev 4, Dev 1, Dev 5) | Engineers who check published data | `config.<env>.yaml` (row policy grantees) |
| Cloud Build service account | Google-managed | CI and CD | Exists already |
| Datastream service agent | Google-managed | Writes `raw_g2` | Exists once the API is on |
| Pub/Sub service agent | Google-managed | Writes `raw_lpos` | Exists once the API is on |
| Log sink writer | Google-managed, per sink | Writes `audit_logs` | Created with the sink |
| BigQuery Data Transfer service agent | Google-managed | Runs the scheduled query | Exists once the API is on |

## 2. BigQuery datasets

Key: **R** = `roles/bigquery.dataViewer`; **W** = `roles/bigquery.dataEditor`; `—` = nothing.
Columns marked `{env}` are granted per environment, so `sa-dwh-writer-dev` gets them on the `_dev` datasets only.

| Identity | raw_g2 | raw_g2_parity | raw_lpos | raw_crm | sim_g2_datalake | keys | stg, prep, build, dq {env} | ops {env} | wh {env} | sec {env} | scale | audit_logs | poc1_baseline |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `sa-simulator` | — | — | — | — | W | — | — | — | — | — | — | — | — |
| `sa-crm-loader` | — | — | — | W | — | — | — | — | — | — | — | — | — |
| `sa-dwh-writer-{env}` | R | — | R | R | R (other project, if any) | R | W | W | W + custom role | W | — | — | — |
| `sa-orchestrator` | R **NEW** | — | R **NEW** | — | — | — | — | W | — | — | — | — | — |
| Tenant users, app tenants | — | — | — | — | — | — | — | — | R | — (spike 1) | R (Day 11, **NEW**) | — | — |
| `sa-test-app` | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `sa-pii-probe` **NEW** | R | — | — | R | — | — | — | — | — | — | — | — | — |
| Internal analyst | — | — | — | — | — | — | — | — | R | — | R | — | — |
| Looker users A and B | — | — | — | — | — | — | — | — | R (`wh_dev` only) | — (spike 1) | — | — | — |
| Cloud Build account | R **NEW** | R | R **NEW** | R **NEW** | R **NEW** | — | — | — | — | — | — | — | — |
| Datastream agent | W | — | — | — | — | — | — | — | — | — | — | — | — |
| Pub/Sub agent | — | — | W | — | — | — | — | — | — | — | — | — | — |
| Log sink writer | — | — | — | — | — | — | — | — | — | — | — | W | — |

- **`sec_{env}`:** if spike 1 says readers need to read `map_tenant_access`, they get **R** here, and the table
  gets its own row policy, `principal = SESSION_USER()`.
- **`scale`:** the benchmark (F6) runs as tenant A and the internal analyst, so both need R on `scale` for Days 11–12.
- **Not in the table:**
  - Engineers' own access comes from their project roles.
  - `dbt_<user>_*` and `dbt_pr_<n>_*` datasets belong to whoever creates them (section 5).

## 3. Project-level and resource grants

| Identity | Project-level roles | Resource-level grants |
|---|---|---|
| `sa-simulator` | `bigquery.jobUser` **NEW** (load jobs into `sim_g2_datalake`) | `cloudsql.client`; `secretmanager.secretAccessor` on `poc-ops-db-simulator`; `pubsub.publisher` on `poc-case-events`; `storage.objectCreator` on the CRM bucket |
| `sa-crm-loader` | `bigquery.jobUser` | `storage.objectViewer` on the CRM bucket |
| `sa-dwh-writer-{env}` | `bigquery.jobUser` | Custom role `pocDwhWriterRls` on `wh_{env}` (section 4); fine-grained reader on `pii_direct` and `pii_indirect`; `storage.objectAdmin` on `…-dbt-artifacts` **NEW**; `artifactregistry.reader` |
| `sa-orchestrator` | `bigquery.jobUser` **NEW** (watchdog query, `log_step`); `logging.logWriter` | `run.developer` on the `poc-*` jobs **CHANGED**; `workflows.invoker`; `cloudsql.editor` (stop and start `poc-ops-db`); `datastream.admin` on `poc-cdc-stream` (pause and resume); `cloudscheduler.admin` (pause and resume) |
| Tenant users, app tenants | `bigquery.jobUser` | — |
| `sa-test-app` | — | `iam.serviceAccountTokenCreator` on `sa-app-tenant-a` and `sa-app-tenant-b` **only** |
| `sa-pii-probe` | `bigquery.jobUser` | `bigquerydatapolicy.maskedReader` on the `pii_direct` data policy (if spike 3 says yes). **No** fine-grained reader |
| Internal analyst | `bigquery.jobUser` | `maskedReader` (if spike 3 says yes) |
| Looker users A and B | `bigquery.jobUser` | — |
| Security-suite runner | — | `iam.serviceAccountTokenCreator` on the tenant users, app tenants, `sa-test-app` and `sa-pii-probe`. **Not** on any writer |
| One named internal person | — | Fine-grained reader on `pii_direct` (checks the real values, D9) |
| BigQuery Data Transfer agent | — | `iam.serviceAccountTokenCreator` on `sa-simulator` **NEW** (runs the scheduled query as it) |
| Pub/Sub agent | — | `pubsub.publisher` on `poc-case-events-dlq`; `pubsub.subscriber` on `poc-case-events-to-bq` |
| Cloud Build account | Whatever `terraform apply` needs (sandbox: broad) | Fine-grained reader on both tags **NEW**; `bigquery.user` to create `dbt_pr_*` datasets |

## 4. Row access and column access

| Control | Granted to |
|---|---|
| `rls_all_rows` on every tenant-scoped `wh_{env}` table | `sa-dwh-writer-{env}`, internal analyst, all-rows operators **NEW** |
| `rls_tenant` on every tenant-scoped `wh_{env}` table | Tenant users, app tenants, Looker users A and B (`dev` only) |
| `store_access` rows (which tenant each principal sees) | Tenant A: `sa-tenant-a-user`, `sa-app-tenant-a`, Looker user A. Tenant B: the same three for B. The planted negative cases are in `specs.md` |
| Custom role `pocDwhWriterRls` | `bigquery.rowAccessPolicies.create`, `.delete`, `.get`, `.getIamPolicy`, `.list`, `.setIamPolicy`, `.update` |

**`pocDwhWriterRls` changes from the plan:**
- `bigquery.tables.setCategory` is dropped: the writer never tags columns (D9 does, through Terraform and the
  tagging script).
- `.get` is added.
- Spike 2 confirms the final list.

## 5. CI and laptops (needed because of tokens and tags)

| Who | Needs | Why |
|---|---|---|
| Cloud Build (`--target ci`) | R on the raw datasets; fine-grained reader on both tags; a **CI token key** from a dbt variable, not `keys.token_key` | `stg_*` reads tagged columns, and `tokenize()` reads the key. Without these, every PR build fails |
| Developers (`--target local`) | The same. The local token key is a fixed test value | Parity (C4) and the batch harness (A12) run as the developer |

Change to C9: `tokenize()` reads `keys.token_key` only for targets `dev` and `int`, and `var('token_key')` otherwise.
Tokens made with the test key never reach `wh`.

## 6. Rules that must hold (checked by AT-27 and D5)

1. No reader has a project-level BigQuery data role. Readers get only job user plus dataset viewer.
2. No reader, and not `sa-test-app`, has token creator or service account user on `sa-dwh-writer-{env}`,
   `sa-orchestrator` or `sa-simulator`.
3. Only the writers, the Cloud Build account, developers and the one named person can read tagged columns in full.
4. `keys` can be read by the writers only.
5. `wh_{env}` can be written by the writers only. `sec_{env}` too.

## 7. Changes from plan section 4.4, and why

| Change | Why |
|---|---|
| `sa-orchestrator`: R on `raw_g2` and `raw_lpos`, plus job user | The watchdog (E7) queries `g2_heartbeat` and `case_event`. The plan gives it `ops` only |
| `sa-orchestrator`: `run.developer` instead of `run.invoker` | The workflow passes arguments to the jobs (`[dbt, source, freshness, …]`). Running a job with overrides needs `run.jobs.runWithOverrides`, which I believe invoker lacks. **[check]** |
| `sa-simulator`: job user; runs the scheduled query | Load jobs need `bigquery.jobs.create`. The plan doesn't say who runs `derived_alert` |
| `sa-dwh-writer`: artifacts bucket | E3 writes `run_results.json` and `manifest.json` there |
| `sa-pii-probe` | D5 case 5 needs an identity that can read `raw_crm` but has no tag. The analyst can't read `raw_crm` at all, so the test would pass without checking tags |
| Security-suite runner | D5 impersonates every reader. Someone has to be allowed to do that, and must not be able to impersonate the writer |
| All-rows operators | Anyone named in no policy sees zero rows. E11's fingerprints would compare two empty results and pass falsely, and F2 would build an empty `scale` |
| R on `scale` for tenant A and the analyst | F6 benchmarks as both |
| Cloud Build and developers: raw access, tags, test key | Section 5 |
| Data Transfer agent: token creator on `sa-simulator` | Required for a scheduled query that runs as a service account |

## 8. Open points

1. Spike 1 decides whether readers need R on `sec_{env}`.
2. Spike 2 confirms `pocDwhWriterRls` and whether a custom role can be granted on one dataset or must be granted on
   the project.
3. Spike 3 decides whether `maskedReader` exists for us (masking), or whether reads without the tag are denied.
4. Whether the Looker users already have project roles as developers. If they do, AT-24 through Looker Studio
   proves isolation, but not read-only access, for those accounts.
5. A Google group for tenant readers would keep the `rls_tenant` grantee list stable (plan D4). Can we create one?
