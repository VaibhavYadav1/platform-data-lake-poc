# POC D: task sequence, with references to the current code

| | |
|---|---|
| **Owner** | POC D owner (Shreyash) |
| **Assignment rule** | Tasks are owned per POC, not per developer, and there is no fixed day plan. Each POC owner finishes their own POC's tasks. A task starts when what it needs is ready |
| **Repos checked** | `platform-data-lake-poc` (clone of `VaibhavYadav1/platform-data-lake-poc`, commit `8f3687a`), `data-lake-ETL-tool`, `data-gen-upload-data-lake-poc`, `workflow-data-lake-poc`, `schema-gen-data-lake-poc`, and the local `poc-d/` work folder |

**Foundation tasks** belong to no POC, so each is assigned to the POC it serves:

| Foundation task | Owner |
|---|---|
| 0.2 Terraform skeleton | POC E |
| 0.3 POC 1 baseline, 0.4 dbt skeleton | POC C |
| 0.5 G2 schema, 0.10 Cloud SQL module | POC A |
| 0.7 specs: tenant and customer rules | POC B |
| 0.7 specs: personal-data inventory | POC D |
| 0.9 spikes | 1–3 POC D; 4–5 POC C; 6 POC E |

## State of the code today

- **`platform-data-lake-poc` holds only folders and a `README.md` per folder.** There's no code yet.
  - Every README still names **"Dev N" and days**, from the old assignment.
  - Update the POC D folders' READMEs to "POC D owner" when you first commit to them.
- **POC 2 reuses existing code:**
  - **G2 table columns:** `data-lake-ETL-tool/app/models/stage/tables/*.py`.
  - **POC 1 warehouse logic:** `data-lake-ETL-tool/app/warehouse_load/transforms.py` and `docs/warehouse-dataset-plan.md`.
  - **Test data:** `data-gen-upload-data-lake-poc/generate_synthetic_data.py`.
  - **Workflow pattern:** `workflow-data-lake-poc/workflow.yaml` (`log_step`, line 51 onwards).
- **POC 1 has no tenant security.** Tenancy is the text column `ultimate_parent` (for example `ALPHA HOLDINGS`), in:
  - `data-lake-ETL-tool/app/models/dwh/tables/dim_store.py:24`;
  - `data-lake-ETL-tool/app/models/dwh/base.py:58,74`.

  POC 2 replaces it with `tenant_id`, the CRM account id (D-23).
- **The plan's schema package isn't here.** The plan refers to `packages/data_lake_schema` for column definitions. It isn't in this repo: `schema-gen-data-lake-poc/README.md` points at the older `dixhanshyugen/platform-data-lake-poc`. Use the `data-lake-ETL-tool` copy of the models.
- **POC D work already done** is in `poc-d/`, not yet in the repo:
  - `docs/poc2/pii-inventory.md`, `access-matrix.md`, `poc-d-security-design.md` and `spikes-poc-d.md`;
  - `scripts/spikes/poc_d/` (setup, policies, spike 1–3 SQL, `run_as.py`, teardown).

---

## Stage 1: Foundation

### 1. POC E: 0.2 Terraform skeleton
- **Code:** `terraform/shared/README.md` and `terraform/env/README.md`, empty. They expect:
  - `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`, `providers.tf`;
  - `dev.tfvars` and `dev.backend.hcl`.
- **Delivers:** the state bucket, provider pins, `default_labels`, and the APIs enabled. The API list includes Data Catalog and BigQuery Data Policy, which D9 needs.
- **For POC D:** steps 9, 10 and 14 are Terraform modules wired into these roots. Terraform v1.17.1 is installed on this laptop.

### 2. POC C: 0.4 dbt skeleton
- **Code:** `dbt/README.md`; `dbt/macros/README.md` lists `generate_schema_name.sql`, whose code is in plan 0.4.
- **Delivers:** the `local`, `ci`, `dev` and `int` targets. The `security` folder gets `+schema: build`.
- **For POC D:** `dbt/models/security/map_tenant_access` (step 20) builds on this.

### 3. POC A: 0.5 G2 schema
- **Code:** `sql/g2/README.md` → `schema.sql`, empty.
- **Reuse:** columns from `data-lake-ETL-tool/app/models/stage/tables/`:
  - `users.py:15-18`: `user_id`, `user_name`, `email`, `team_id`;
  - `alert_incidents.py:22`: `assigned_user_id`;
  - `alert_history.py:29-30`: `changed_by_user_id`, `comments`.
- **Adds** two new tables: `store_access(principal, crm_account_id)` and `heartbeat`.
- **For POC D:**
  - `store_access` is the source of tenant access.
  - `users` holds the names and emails D9 tags.
  - **Review point:** `store_access.principal` must be a full email, which is what `SESSION_USER()` returns.

### 4. POC B: 0.7 specs, the customer and tenant part
- **Code:** `docs/poc2/specs.md`, "To be written". `dbt/seeds/README.md` lists `map_customer_type.csv` (B6).
- **Reuse:** brands in `data-gen-upload-data-lake-poc/generate_synthetic_data.py:88-93`:
  - B01 and B02 → ALPHA HOLDINGS;
  - B03 → BETA RETAIL GROUP;
  - B04 → GAMMA RETAIL, which has no stores.
- **Delivers:**
  - tenant A = `ACC-1001`, tenant B = `ACC-1002`, vendor `ACC-2001` (S137, S138);
  - S136 and S140 have no CRM record;
  - the test principals and their `store_access` rows.
- **For POC D:** your test data, and the expected row counts for D5 case 1.

### 5. POC D: 0.7 personal-data inventory
- **Code:** done in `poc-d/docs/poc2/pii-inventory.md`. It belongs in section 6 of `docs/poc2/specs.md`.
- **Covers:**
  - G2: `user_name`, `email`, `user_id`, `assigned_user_id`, `changed_by_user_id`, `comments`, `store_access.principal`;
  - CRM: `primary_contact_name`, `primary_contact_email`;
  - LPOS: `offender_token`, `attributes`.
- **Next:** agree its 6 open decisions with the POC B and POC C owners, then merge it into `specs.md`.

### 6. POC D: D1 / 0.9 spikes 1–3
- **Code:** ready in `poc-d/scripts/spikes/poc_d/`:
  - `00_setup.sh`, `01_setup.sql`, `02_policies.sql`;
  - `spike1/`, `spike2/`, `spike3/`;
  - `run_as.py`, `99_teardown.sh`;
  - run order in `README.md`.
- **Results go in:** `platform-data-lake-poc/docs/poc2/spikes.md` ("To be written"), using the template `poc-d/docs/poc2/spikes-poc-d.md`.
- **Before running:**
  - set `ME` in `spike.env`;
  - `pip install google-cloud-bigquery google-auth`;
  - `gcloud auth application-default login`;
  - confirm Owner-level rights on `gks-datalake-poc2-dev`.
- **Answers:**

  | Spike | Question | Decides |
  |---|---|---|
  | 1 | Does a row-policy subquery work for readers who can't read the mapping? | Whether readers need access to `sec_{env}` |
  | 2 | Does DML work under row policies? | Whether the publish design (E5) holds, and the permissions of `pocDwhWriterRls` |
  | 3 | Is masking available to us? | Masking versus "denied without the tag" in D9 |

### 7. POC C: 0.9 spike 4 (native views over row policies) and spike 5 (`CREATE TABLE LIKE`)
- **Code:** `orchestration/publish/objects/README.md`, empty.
- **For POC D:** decides whether `mv_cart_count_daily` and `mv_alert_trend_daily` can face tenants.

### 8. POC E: 0.9 spike 6 (one transaction over about 20 tables)
- **For POC D:** if it must split into two transactions, readers may briefly see dimensions and facts from different publishes. D5 case 7 then has to allow for that.

---

## Stage 2: Sources and identities

### 9. POC D: D2 identities and IAM
- **Code:** `terraform/modules/service_accounts/README.md`, empty.
- **Input:** `poc-d/docs/poc2/access-matrix.md`, drafted.
- **Build** these service accounts:
  - `sa-dwh-writer-dev`;
  - `sa-orchestrator`, `sa-simulator`, `sa-crm-loader`;
  - `sa-tenant-a-user`, `sa-tenant-b-user`;
  - `sa-test-app`, `sa-app-tenant-a`, `sa-app-tenant-b`;
  - proposed: `sa-pii-probe`.
- **Grants:**
  - dataset-level viewer and editor;
  - job user;
  - token creator on `sa-app-tenant-*` for `sa-test-app` only.
- **Custom role `pocDwhWriterRls`:**
  - `bigquery.rowAccessPolicies.create`, `update`, `delete`, `get`, `list`, `getIamPolicy`, `setIamPolicy`;
  - spike 2 confirms the list.
- **Wire it into** `terraform/env/main.tf`, which comes from step 1.
- **Done when:** applied, and the access matrix is copied into `docs/poc2/security-report.md`.

### 10. POC D: audit sink (moved earlier from D8)
- **Code:** `terraform/modules/audit_sink/README.md`, empty.
- **Build:**
  - `google_logging_project_sink` `poc-bq-audit` into the `audit_logs` dataset;
  - filter: `bigquery.googleapis.com` **and** `iamcredentials.googleapis.com`, so impersonation attempts are logged too;
  - editor on `audit_logs` for the sink's writer identity.
- **Why now:** the D5 runs in step 26 need audit evidence.

### 11. POC A: 0.10 and A1, A2 Cloud SQL and replication
- **Code:**
  - `terraform/modules/cloudsql_g2/README.md`, empty;
  - `sql/g2/replication.sql`, empty (its code is in plan A2).
- **For POC D:** none directly. It's needed by step 12.

### 12. POC A: A4 Datastream into `raw_g2`
- **Code:** `terraform/modules/datastream_pg/README.md`, empty.
- **Delivers:** `raw_g2.g2_users`, `raw_g2.g2_store_access` and the rest.
- **For POC D:**
  - the **`raw_g2_parity` snapshot** is taken here, before tagging, so it's an untagged copy of names and emails;
  - ask the POC A owner to re-take it after step 14, or tag it as well;
  - spike `s3f` tells you whether snapshots keep tags.

### 13. POC B: B3 CRM loader into `raw_crm`
- **Code:** `terraform/modules/crm_landing/README.md` and `loaders/crm/README.md`, empty.
- **Delivers:** `raw_crm.account_landing`, with `primary_contact_name` and `primary_contact_email`.
- **For POC D:** the Terraform schema of `account_landing` is where the policy tags go (step 14).

### 14. POC D: D9 policy taxonomy, tags, masking
- **Code:**
  - `terraform/modules/policy_tags/README.md`, empty;
  - `scripts/security/README.md` lists `tag_raw_columns.py`, empty.
- **Build:**
  1. Taxonomy `poc-pii` (`us-central1`), tag `pii_direct`, in `modules/policy_tags`.
  2. `policy_tags` on the two contact columns in the `crm_landing` schema. That's the POC B module, so make it a small PR for the POC B owner to review.
  3. `tag_raw_columns.py` tags `raw_g2.g2_users.user_name` and `email`. Datastream owns that table, so re-run the script if it's recreated.
  4. Fine-grained reader: `sa-dwh-writer-dev`, `sa-dwh-writer-int` and one tester.
  5. If spike 3 says yes: a SHA-256 data policy, with masked reader for the internal analyst and `sa-pii-probe`.
  6. Check that Datastream and `poc-crm-loader` still write. If either fails, grant it fine-grained reader.
- **Spike reference:** `poc-d/scripts/spikes/poc_d/spike3/s3_setup.sh` has the working gcloud and REST calls.
- **Done when:** AT-28 (raw part) passes.

---

## Stage 3: Models

### 15. POC A: A10 G2 staging views
- **Code:** `dbt/models/staging/g2/README.md` → `stg_g2__<table>` using `cdc_current_state()` (`dbt/macros/README.md`).
- **For POC D:** `stg_g2__store_access` is the input to `map_tenant_access`. It must carry `is_deleted`, so revokes work.

### 16. POC B: B6 `dim_account`
- **Code:**
  - `dbt/models/marts/crm/README.md` → `dim_account`;
  - `dbt/macros/README.md` → `is_customer.sql`;
  - `dbt/seeds/README.md` → `map_customer_type.csv`.
- **For POC D:** gives `account_id`, `tenant_id` (top-level account) and `is_customer`, which the D3 join needs.

### 17. POC B: B7 `int_store__tenant`
- **Code:** `dbt/models/intermediate/tenant/README.md` → `int_store__tenant` (G2 store → CRM store → account → top-level account).
- **For POC D:** puts `tenant_id` on `dim_store`, and through the store on every fact.
- **Raise with the POC B owner:**
  - a vendor child account under a customer parent inherits the customer's `tenant_id`;
  - a parent cycle breaks the walk up the hierarchy.

### 18. POC C: C9 tokens and DQ41
- **Code:** `dbt/macros/README.md` → `tokenize.sql`. `scripts/security/README.md` → `load_token_key.py`.
- **Replaces** POC 1's plain `name` and `email` in `data-lake-ETL-tool/app/models/dwh/tables/dim_user.py:20-21`. `dim_user` isn't ported.
- **For POC D:**
  - this is AT-28's warehouse part;
  - ask for `changed_by_user_id` → `changed_by_token`;
  - ask for an allow-list entry for `store_access.principal`;
  - ask for a test key for the `ci` and `local` targets.

### 19. POC C: C2, C3, C5, C10 warehouse tables with `tenant_id`
- **Code:**
  - `dbt/models/marts/core/README.md`: `dim_store`, `dim_device`, `dim_alert_type`, `fct_alert`, `fct_alert_history`;
  - `marts/wheel`: `dim_wheel`, `fct_wheel_event`;
  - `marts/lpos`: `fct_case`, `dim_offender`;
  - `marts/crm`: `fct_work_order`;
  - `rollups`: the `mv_*` marts.
- **Reuse:** `data-lake-ETL-tool/app/warehouse_load/transforms.py` (joins) and `docs/warehouse-dataset-plan.md`.
- **For POC D:** the tables your policies protect. Every one except `dim_date`, `dim_alert_type` and the status seed must have `tenant_id`.

### 20. POC D: D3 tenant rules and `map_tenant_access`
- **Code:** `dbt/models/security/README.md` → `map_tenant_access` (`.sql` and `.yml`), empty.
- **Build:**
  1. **Tenant rules:** which principals map to which account. Add the test `store_access` rows to the simulator seed in `data-gen-upload-data-lake-poc/simulator/`, which doesn't exist yet; it's a POC A deliverable, so send your rows to the POC A owner.
  2. **The model:**
     ```sql
     select distinct a.principal, acc.tenant_id
     from {{ ref('stg_g2__store_access') }} a
     join {{ ref('dim_account') }} acc  on acc.account_id = a.crm_account_id
     join {{ ref('dim_account') }} root on root.account_id = acc.tenant_id
     where not a.is_deleted and root.is_customer
     ```
     The second join checks `is_customer` on the top-level account, not the child. This fixes a gap in the plan.
  3. **The `.yml`:** `unique` on (`principal`, `tenant_id`); `not_null`; a relationships test to `dim_account`.
- **Done when:** one row per (principal, tenant), customer tenants only (AT-19 check 2).

---

## Stage 4: Publish and protect

### 21. POC E: E3 dbt runner job
- **Code:**
  - `terraform/modules/run_jobs/README.md`;
  - the dbt `Dockerfile` and `entrypoint.sh` (plan 0.4 and E3).
- **For POC D:** runs as `sa-dwh-writer-dev`, the identity you created in step 9.

### 22. POC D: D4 row access policies
- **Code:** `orchestration/publish/policies/README.md`, empty.
- **Reuse:** `poc-d/scripts/spikes/poc_d/02_policies.sql`, already proven by the spikes.
- **Build:**
  - `policies/all_rows.sql` and `policies/tenant.sql`, using the placeholders `{project}`, `{env}`, `{table}`, `{all_rows_principals}`, `{tenant_principals}` (plan D4);
  - apply them by hand to every tenant-scoped `wh_dev` table until step 24 takes over.
- **Rule:** the writer must be in `rls_all_rows`.
- **Done when:** both policies are on every tenant-scoped `wh_dev` table.

### 23. POC C: C11 `tables.yaml`
- **Code:** `orchestration/publish/README.md` → `tables.yaml`.
- **For POC D:** `tenant_scoped: true` decides which tables get your policies. Check the list against step 19.

### 24. POC E: E5 `publish.py`
- **Code:** `orchestration/publish/README.md` → `publish.py`, plus `config.dev.yaml`, which holds your grantee lists.
- **For POC D:**
  - step 3 re-applies your policies on every publish;
  - step 5 checks that they exist;
  - the hash in `ops_{env}.publish_policy_state` triggers `CREATE OR REPLACE` when a grantee changes.
- **Ask for:** a check that the writer is in `rls_all_rows`.

### 25. POC E: E4 micro-batch workflow
- **Code:** `orchestration/README.md` → `micro_batch.workflow.yaml`.
- **Reuse:** the `log_step` pattern in `workflow-data-lake-poc/workflow.yaml` (from line 51).
- **For POC D:** D6 needs this running, because a revoke only takes effect when the next run publishes the mapping.

---

## Stage 5: Prove it

### 26. POC D: D5 security suite
- **Code:** `scripts/security/README.md` → `test_access.py` (pytest), empty.
- **Reuse:** the impersonation and PASS/FAIL logic in `poc-d/scripts/spikes/poc_d/run_as.py` (`impersonated_credentials`, error classification).
- **Cases:**
  1. Own rows, and other tenants' rows = 0.
  2. Writes and DDL in `wh`: denied.
  3. Reads of `raw_*`, `stg`, `prep`, `build`, `dq`, `ops`, `keys`: denied.
  4. Impersonating the writer: denied.
  5. `sa-pii-probe` reads a contact email: masked, or denied.
  6. Vendor, NULL-tenant and `S-PROBE` stores: not visible.
  7. No mixed versions during a publish.
- **Results go to** `ops_dev.security_test_result`.
- **Done when:** AT-24 (command line) and AT-27 pass.

### 27. POC D: D7 test app
- **Code:** `apps/tenant_reader/README.md`, empty.
- **Build:** `python -m tenant_reader --tenant A --query store_health`.
  - It runs as `sa-test-app` and impersonates `sa-app-tenant-a` or `-b`.
  - Its queries are parameterised, with `maximum_bytes_billed`.
  - Negative tests: tenant A filtering on B's id → 0 rows; impersonating the writer → refused.
- **Done when:** AT-24 (app) passes.

### 28. POC D: D6 access-removal test
- **Code:** a script in `scripts/security/` or `scripts/acceptance/` (`run_all.py` is listed there).
- **Uses** the simulator's `revoke` and `grant` commands (plan 0.6). That's POC A's simulator package, which doesn't exist yet.
- **Done when:** AT-25 passes: 0 rows within 20 minutes, back after `grant`.

### 29. POC C: DQ41 and the daily email scan pass
- **For POC D:** this is AT-28's warehouse part. Link its result in the security report.

### 30. POC D: D8 evidence and security report
- **Code:** `docs/poc2/security-report.md`, "To be written".
- **Build:** for each denied attempt from step 26, show its `audit_logs` entry and its row in `INFORMATION_SCHEMA.JOBS_BY_PROJECT` with `accessDenied`.
- **Done when:** every blocked attempt is linked (AT-27).

### 31. POC E: E11 forced failure
- **For POC D:** pass requires both policies still on every tenant-scoped table (AT-29). The fingerprint check must run as an identity in `rls_all_rows`, or it passes falsely.

### 32. POC E: E9 `int` environment
- **Code:** `terraform/env/README.md` → `int.tfvars`, `int.backend.hcl`.
- **For POC D:**
  - your modules must take `env` as a variable, which creates `sa-dwh-writer-int` and the `int` grants;
  - the tenant cases run in `int` (AT-31).

### 33. POC F: F5 Looker Studio report
- **For POC D:**
  - data credentials must be **Viewer**;
  - the `fct_alert` source must use `alert_date` as the date range, because a partition filter is required.

### 34. POC D: D10 Looker Studio tenant check
- **Build:** two team members' Google accounts, mapped to tenant A and tenant B in `store_access`, plus the internal analyst. They open the same report.
- **Done when:** they see different rows, and screenshots are in `security-report.md` (AT-24, dashboard).

### 35. POC F: F2 and F6 scale data and benchmark
- **Code:** `scripts/scale/README.md` → `build_scale.sql`.
- **For POC D:** `scale.map_tenant_access` and the same policies, from your `policies/*.sql`. The benchmark compares the internal identity (all rows) with tenant A (tenant policy).

### 36. POC E with POC D: E12 destroy and re-apply `int`
- **For POC D:** your Terraform must rebuild with no console steps, and the security cases must pass again (AT-35).

---

## Stage 6: Close

37. **POC D:** finish `docs/poc2/security-report.md`: access matrix, suite results, audit evidence, Looker Studio screenshots and spike conclusions.
38. **POC D:** remove the Looker Studio users' `store_access` rows and their grants.
39. **All POC owners:** demo, then teardown per `docs/poc2/runbook.md`. Run `poc-d/scripts/spikes/poc_d/99_teardown.sh` if the spike resources are still there.

---

## POC D at a glance

| Step | Task | Repo location | Status |
|---|---|---|---|
| 5 | Personal-data inventory | `docs/poc2/specs.md` §6 | Drafted in `poc-d/` |
| 6 | D1 spikes 1–3 | `docs/poc2/spikes.md` | Kit ready in `poc-d/`; not yet run |
| 9 | D2 identities and IAM | `terraform/modules/service_accounts` | Matrix drafted |
| 10 | Audit sink | `terraform/modules/audit_sink` | Not started |
| 14 | D9 tags and masking | `terraform/modules/policy_tags`, `scripts/security/tag_raw_columns.py` | Rehearsed in spike 3 |
| 20 | D3 mapping | `dbt/models/security/map_tenant_access` | Not started |
| 22 | D4 row policies | `orchestration/publish/policies/` | Rehearsed in `02_policies.sql` |
| 26 | D5 security suite | `scripts/security/test_access.py` | Impersonation logic in `run_as.py` |
| 27 | D7 test app | `apps/tenant_reader/` | Not started |
| 28 | D6 access removal | `scripts/security/` | Waits on POC A's simulator and POC E's micro-batch |
| 30 | D8 evidence | `docs/poc2/security-report.md` | Not started |
| 34 | D10 Looker Studio | `docs/poc2/security-report.md` | Waits on POC F |
| 37–38 | Report and clean-up | `docs/poc2/security-report.md` | – |
