# POC 2: Operations Runbook

**Status:** Draft. Not yet followed by a second developer, which is the E13 "done when". Commands marked
"(not written yet)" refer to scripts or modules other tasks still have to deliver.  
**Owner:** Dev 4  
**Task:** E13

This runbook is for someone who didn't build the system. It covers day-to-day operations, troubleshooting, and teardown.

---

## Contents

1. [One-time Setup](#1-one-time-setup)
2. [Pause and Resume](#2-pause-and-resume)
3. [Approve a Held CRM Export](#3-approve-a-held-crm-export)
4. [Re-run a Failed Job](#4-re-run-a-failed-job)
5. [Reservations](#5-reservations)
6. [Teardown](#6-teardown)
7. [Where to Look](#7-where-to-look)

---

## 1. One-time Setup

These steps run **once** when setting up a new environment. After teardown and rebuild, run them again.

### 1.1 Create the Terraform State Bucket

**What it is:** GCS bucket that stores Terraform's state files. Must exist before `terraform init`.

**Command:**
```bash
gsutil mb -p <project-id> -c STANDARD -l us-central1 gs://<project-id>-tfstate
gsutil versioning set on gs://<project-id>-tfstate
```

**Example:**
```bash
gsutil mb -p gks-datalake-poc2-dev -c STANDARD -l us-central1 gs://gks-datalake-poc2-dev-tfstate
gsutil versioning set on gs://gks-datalake-poc2-dev-tfstate
```

**Verify:**
```bash
gsutil ls gs://<project-id>-tfstate
```

**Record this command** in your team's setup notes. If the bucket is accidentally deleted, Terraform can't initialize.

---

### 1.2 Bootstrap Cloud SQL `g2` Schema

**What it is:** Runs the SQL that creates the G2 database schema, the users, the publication and the replication slot.

**Prerequisites:**
- Cloud SQL instance `poc-ops-db` exists and is running
- Three secrets in Secret Manager: `poc-ops-db-postgres`, `poc-ops-db-datastream`, `poc-ops-db-simulator`
- The Cloud SQL Auth Proxy is installed

**Run it:**
```bash
# Terminal 1: the Auth Proxy
cloud-sql-proxy gks-datalake-poc2-dev:us-central1:poc-ops-db --port 5433

# Terminal 2: the bootstrap
python scripts/g2_bootstrap.py
```

Options: `--host`, `--port` (default 5433), `--db` (default `g2`), `--user`, `--local` (rehearse against a local
Docker PostgreSQL) and `--check` (only run the checks).

**What it does:**
1. Runs `sql/g2/schema.sql` (schema `g2` and its 11 tables)
2. Runs `sql/g2/replication.sql` (`datastream_user`, `simulator_user`, grants, publication `poc_pub`)
3. Creates the replication slot `poc_slot` on its own, because PostgreSQL refuses to create a logical slot in a transaction that has already written
4. Runs the checks and exits 1 if anything is missing

**Run it once.** It refuses if anything already exists. `--check` re-runs only the checks. If Cloud SQL is recreated, run it again.

---

### 1.3 Load the Token Key

**What it is:** Writes the secret key for personal-data tokens into the `keys.token_key` BigQuery table.

**Status (not written yet):** the script is Dev 5's task C9. The command below is the intended one.

**Prerequisites:**
- Secret `poc-token-key` exists in Secret Manager
- BigQuery dataset `keys` exists

**Script:**
```bash
python scripts/security/load_token_key.py --env dev
```

**What it does:**
- Reads the key from Secret Manager
- Writes one row to `keys.token_key`
- Only `sa-dwh-writer-{env}` can read this table

**Run it once per environment.** The table is never recreated, so the key persists.

---

### 1.4 Create the Second Project (Optional)

**What it is:** A separate project for `sim_g2_datalake`, to test cross-project reads.

**If you have permission to create projects:**
```bash
gcloud projects create data-lake-poc-src-<suffix> \
  --folder=<folder-id> \
  --set-as-default=false

gcloud beta billing projects link data-lake-poc-src-<suffix> \
  --billing-account=<billing-account-id>
```

**Update Terraform:** set the second project's id in the variable that the `sim_g2_datalake` module defines (the module is not written yet; see its README).

**If you don't have permission:** Use a dataset in the main project instead. Update `terraform/modules/sim_g2_datalake` accordingly.

---

### 1.5 Looker Studio Setup

**What it is:** One-time setup for the tenant isolation dashboard (F5, AT-24).

**Steps:**
1. Create a Looker Studio report: https://lookerstudio.google.com/
2. Add two data sources:
   - `wh_dev.mv_store_health` (BigQuery connector)
   - `wh_dev.fct_alert` (BigQuery connector)
3. Set **Data credentials** to **Viewer's credentials** on both
4. On `fct_alert`, tick **"Use alert_date as date range dimension"**
5. Add charts:
   - Store health table: `store_id`, `colour`, `reason`, `owner`
   - Count by colour: `COUNT(store_id)` grouped by `colour`
   - Alert trend: `COUNT(*)` by `alert_date`
   - Include `tenant_id` column in one table (for screenshots)
6. Share with:
   - Internal analyst (team member)
   - `sa-tenant-a-user`
   - `sa-tenant-b-user`
   - Two team members mapped to tenants A and B

**Record the report URL** in your notes. This is used for AT-24 and D10.

---

## 2. Pause and Resume

The pipeline runs 24/7 by default. Pause it to save cost, or to freeze state during investigation.

### 2.1 Pause Manually

**Stop everything:**
```bash
# Pause all scheduler jobs
gcloud scheduler jobs pause poc-simulator --location=us-central1
gcloud scheduler jobs pause poc-micro-batch-dev --location=us-central1
gcloud scheduler jobs pause poc-micro-batch-int --location=us-central1
gcloud scheduler jobs pause poc-watchdog --location=us-central1
gcloud scheduler jobs pause poc-full-load-dev --location=us-central1
# The int jobs (micro-batch, full-load) exist only after E9; "not found" for them is expected before that.
gcloud scheduler jobs pause poc-full-load-int --location=us-central1

# Pause Datastream
gcloud datastream streams update poc-cdc-stream \
  --location=us-central1 \
  --state=PAUSED

# Stop Cloud SQL
gcloud sql instances patch poc-ops-db --activation-policy=NEVER
```

**Verify:**
```bash
gcloud scheduler jobs list --location=us-central1
gcloud datastream streams describe poc-cdc-stream --location=us-central1
gcloud sql instances describe poc-ops-db --format="value(settings.activationPolicy)"
```

---

### 2.2 Resume Manually

**Start everything:**
```bash
# Start Cloud SQL first
gcloud sql instances patch poc-ops-db --activation-policy=ALWAYS

# Wait for Cloud SQL to be ready
gcloud sql instances describe poc-ops-db --format="value(state)"
# Wait until state is RUNNABLE

# Resume Datastream
gcloud datastream streams update poc-cdc-stream \
  --location=us-central1 \
  --state=RUNNING

# Resume simulator first
gcloud scheduler jobs resume poc-simulator --location=us-central1

# Wait 5 minutes for data to arrive

# Resume the pipeline jobs
gcloud scheduler jobs resume poc-micro-batch-dev --location=us-central1
gcloud scheduler jobs resume poc-micro-batch-int --location=us-central1
gcloud scheduler jobs resume poc-watchdog --location=us-central1
gcloud scheduler jobs resume poc-full-load-dev --location=us-central1
gcloud scheduler jobs resume poc-full-load-int --location=us-central1
```

**Why the order matters:**
1. Cloud SQL must be running before Datastream can resume
2. Datastream must be running before the simulator writes data
3. Wait 5 minutes so the first freshness check sees new data

---

### 2.3 Automatic Pause/Resume (Night-off and Morning-on)

**What it is:** Workflows that automatically pause the pipeline at night and resume it in the morning.

**Default schedule:**
- **Night-off:** 20:00, Monday to Friday (team's time zone)
- **Morning-on:** 08:00, Monday to Friday

**What night-off pauses:** the simulator, `poc-micro-batch-dev` and `-int`, and `poc-watchdog`. It does **not** pause
`poc-full-load-<env>`: the full load runs at 20:15, after night-off, and reads only BigQuery.

**Check if they're enabled:**
```bash
gcloud scheduler jobs describe poc-night-off --location=us-central1 --format="value(state)"
gcloud scheduler jobs describe poc-morning-on --location=us-central1 --format="value(state)"
```

**Pause them (for a 24-hour continuous run):**
```bash
gcloud scheduler jobs pause poc-night-off --location=us-central1
gcloud scheduler jobs pause poc-morning-on --location=us-central1
```

**Resume them:**
```bash
gcloud scheduler jobs resume poc-night-off --location=us-central1
gcloud scheduler jobs resume poc-morning-on --location=us-central1
```

**Run them manually:**
```bash
# Stop everything now
gcloud workflows run poc-night-off --location=us-central1

# Start everything now
gcloud workflows run poc-morning-on --location=us-central1
```

**Check execution status:**
```bash
gcloud workflows executions list poc-night-off --location=us-central1 --limit=5
gcloud workflows executions describe <execution-id> --workflow=poc-night-off --location=us-central1
```

---

### 2.4 Enable the Scheduler Jobs for the First Time

Terraform creates every scheduler job **paused**. Run each workflow once by hand first, then enable its job.

| Job | How to enable |
|-----|---------------|
| `poc-micro-batch-<env>`, `poc-watchdog` | By hand: `gcloud scheduler jobs resume <job> --location=us-central1`. Terraform ignores `paused` on these (night-off and morning-on change it), so setting a variable does nothing. |
| `poc-night-off`, `poc-morning-on`, `poc-full-load-<env>` | Set `night_off_schedule_paused = false` in `terraform/shared/terraform.tfvars` and apply, or resume by hand. |

Do not enable `poc-watchdog` before the simulator and the Datastream stream run, or it logs `watchdog_stale` every 5 minutes.

---

## 3. Approve a Held CRM Export

**What it is:** The CRM loader has a change-size guard (B5). If more than 50% of rows change between exports, the loader holds the export and waits for manual approval.

### 3.1 Check if an Export is Held

**Query** (the loader, task B3, defines the columns: confirm them with `bq show raw_crm.load_log`):
```sql
SELECT folder, status, row_count, changed_pct, loaded_at, error
FROM `<project>.raw_crm.load_log`
WHERE status = 'HELD'
ORDER BY loaded_at DESC
LIMIT 5;
```

**You'll see:**
```
folder: crm/export_ts=20261124T150000/
status: HELD
changed_pct: 0.63  (63% of rows changed)
```

**Check the alert email:** The guard logs `crm_guard_tripped` at `ERROR`, which triggers an email.

---

### 3.2 Approve the Export

**After confirming the change is legitimate** (not a data error), approve it:

```bash
gcloud run jobs execute poc-crm-loader \
  --region=us-central1 \
  --args="--approve,export_ts=20261124T150000" \
  --wait
```

**What it does:**
- Runs the loader with `--approve export_ts=<timestamp>`
- Loads the held export

**Verify:**
```sql
SELECT folder, status, loaded_at
FROM `<project>.raw_crm.load_log`
WHERE folder = 'crm/export_ts=20261124T150000/';
-- status should now be LOADED
```

---

### 3.3 Reject the Export

The plan defines only the approve command (B5). To drop a held export, ask Dev 3, who owns the loader. Do not edit
`raw_crm.load_log` or delete files by hand: only the loader writes `raw_crm`.

---

## 4. Re-run a Failed Job

### 4.1 Re-run a Failed Micro-batch

**Check recent runs:**
```sql
SELECT run_id, started_at, status, error
FROM `<project>.ops_dev.pipeline_run_steps`
WHERE DATE(started_at) = CURRENT_DATE()
ORDER BY started_at DESC
LIMIT 10;
```

**Find the failed run** and check which step failed:
```sql
SELECT step, status, error, started_at
FROM `<project>.ops_dev.pipeline_run_steps`
WHERE run_id = '<run-id>'
ORDER BY started_at;
```

**Re-run the workflow:**
```bash
gcloud workflows run poc-micro-batch-dev --location=us-central1
```

**Common failures and fixes:**

| Failure | Cause | Fix |
|---------|-------|-----|
| `load_crm` step failed | CRM export incomplete or held | Approve the held export (section 3.2) |
| `build_publish` failed | dbt test failed | Open the log of the Cloud Run job `poc-dbt-runner-dev`; the failing test is named there |
| `freshness` failed | The `freshness_check` macro itself errored. A stale source does **not** fail this step: it logs `freshness_breach` and emails | Read the step's error in `pipeline_run_steps`. For a stale source see section 7.3 |
| `build_publish` failed | publish.py failed | Check row policies exist: `bq ls --row_access_policies wh_dev.fct_alert` |

---

### 4.2 Re-run a Failed Full Load

**Check the log:**
```sql
SELECT run_id, started_at, finished_at, status, error
FROM `<project>.ops_dev.full_load_log`
ORDER BY started_at DESC
LIMIT 5;
```

**Re-run the workflow:**
```bash
gcloud workflows run poc-full-load-dev --location=us-central1
```

**What the two checks do to the run:** DQ39 drift makes the run **fail** (exit code 3) *after* the full rebuild has been
published. DQ41 (an email-like value in `build`) stops the run *before* anything is published.

**Check DQ39 results:**
```sql
SELECT entity, incremental_only, full_refresh_only, total_diff, checked_at
FROM `<project>.ops_dev.dq_result`
WHERE check_id = 'DQ39'
ORDER BY checked_at DESC;
```

**If DQ39 shows drift** (non-zero `total_diff`):
1. Identify which fact has drift
2. Check the incremental logic in `dbt/models/marts/<fact>.sql`
3. Look for late-arriving changes outside the lookback window
4. Raise with the dbt owner (Dev 1 or Dev 3)

---

### 4.3 Manually Trigger dbt Build

**If you need to test dbt without the full workflow:**

```bash
# Run dbt locally (requires dbt installed and profiles.yml configured)
cd dbt
dbt build --target dev

# Or run the Cloud Run job directly
gcloud run jobs execute poc-dbt-runner-dev \
  --region=us-central1 \
  --args="dbt,build,--target,dev" \
  --wait
```

**To run only specific models:**
```bash
gcloud run jobs execute poc-dbt-runner-dev \
  --region=us-central1 \
  --args="dbt,build,--select,fct_alert,--target,dev" \
  --wait
```

---

## 5. Reservations

**What they are:** BI Engine and Enterprise Edition reservations for the benchmark (POC F). They cost money per hour, so create them only when needed and destroy them immediately after.

### 5.1 Create Reservations

The reservations module (F4) is not written yet; the variable and reservation names below come from the plan and the module's README.

**Edit `terraform/shared/terraform.tfvars`:**
```hcl
# From Day 11 noon
enable_bi_engine = true

# Or from Day 12 morning
enable_enterprise_reservation = true
```

**Apply:**
```bash
cd terraform/shared
terraform apply
```

**Verify BI Engine:**
```bash
bq show --reservation --location=us-central1 --project_id=<project>
```

**Verify Enterprise:**
```bash
bq show --reservation --project_id=<project> --location=us-central1 poc-bench-enterprise
bq show --reservation_assignment --project_id=<project> --location=us-central1
```

---

### 5.2 Destroy Reservations

**CRITICAL:** Reservations cost per hour. Destroy them as soon as the benchmark is done.

**Edit `terraform/shared/terraform.tfvars`:**
```hcl
enable_bi_engine = false
enable_enterprise_reservation = false
```

**Apply:**
```bash
cd terraform/shared
terraform apply
```

**Verify in console:**
1. Open: https://console.cloud.google.com/bigquery/admin/reservations
2. Check: No reservations exist
3. Check: BI Engine capacity is 0

**Also verify programmatically:**
```bash
bq ls --reservation --location=us-central1 --project_id=<project>
# Should return empty or only default-pipeline

bq show --capacity_commitment --location=us-central1 --project_id=<project>
# Should show no active commitments
```

**Record the destruction time** in the Day 12 checklist.

---

## 6. Teardown

**What it is:** Shut down the POC on Day 12 to stop costs. Keep what the team decides; delete the rest.

### 6.1 Pre-teardown Checklist

**Before tearing down, confirm:**
- [ ] All acceptance tests passed and evidence saved
- [ ] Benchmark results and cost model written
- [ ] Security report complete with screenshots
- [ ] dbt docs and lineage screenshots saved
- [ ] Reservations destroyed (section 5.2)
- [ ] `scale` dataset deleted (section 6.3)

---

### 6.2 Pause Everything

**Stop the pipeline but keep the resources:**
```bash
# Pause all scheduler jobs
for job in poc-simulator poc-micro-batch-dev poc-micro-batch-int \
           poc-watchdog poc-full-load-dev poc-full-load-int \
           poc-night-off poc-morning-on; do
  gcloud scheduler jobs pause $job --location=us-central1
done

# Pause the stream BEFORE stopping Cloud SQL: a stream left running behind a stopped database,
# or paused late, makes the write-ahead log fill the disk. Wait until it shows PAUSED.
gcloud datastream streams update poc-cdc-stream --location=us-central1 --state=PAUSED
gcloud datastream streams describe poc-cdc-stream --location=us-central1 --format="value(state)"

# Stop Cloud SQL
gcloud sql instances patch poc-ops-db --activation-policy=NEVER
```

**This stops costs from:**
- Cloud Run job executions
- Cloud SQL compute (storage still costs)
- Datastream replication

---

### 6.3 Delete Expensive Resources

**Delete the `scale` dataset** (10 GB, used only for benchmarks):
```bash
bq rm -r -f -d <project>:scale
```

**Also remove it from Terraform:**
```bash
# In terraform/shared, comment out or delete the scale module call
cd terraform/shared
terraform apply  # This confirms the dataset is unmanaged
```

**Delete old dbt artifacts:**
```bash
gsutil -m rm -r gs://<project>-dbt-artifacts/dev/*
gsutil -m rm -r gs://<project>-dbt-artifacts/int/*
```

---

### 6.4 Full Teardown (Optional)

**If the team decides to tear down everything:**

```bash
# Each environment has its own state: initialise it before every destroy
cd terraform/env
terraform init -reconfigure "-backend-config=int.backend.hcl"
terraform destroy "-var-file=int.tfvars"
terraform init -reconfigure "-backend-config=dev.backend.hcl"
terraform destroy "-var-file=dev.tfvars"

# Destroy shared resources last
cd ../shared
terraform init -reconfigure "-backend-config=backend.hcl"
terraform destroy "-var-file=terraform.tfvars"
```

Destroying `shared` also removes the Cloud Build service accounts and triggers, so nothing deploys automatically afterwards.

**What survives:**
- Terraform state bucket (manual deletion)
- Raw data in `poc_dwh_dev` and `poc_analytics_dev` (Phase 1 resources)
- Cloud Build history
- Audit logs

**What's deleted:**
- All `*_dev` and `*_int` datasets
- Cloud SQL instance
- Datastream stream
- Cloud Run jobs
- Workflows
- GCS buckets (dbt-docs, CRM exports, dbt artifacts)

---

## 7. Where to Look

### 7.1 Run Logs

**Micro-batch runs:**
```sql
SELECT run_id, step, status, error, started_at
FROM `<project>.ops_dev.pipeline_run_steps`
WHERE DATE(started_at) = CURRENT_DATE()
ORDER BY started_at DESC;
```

**Full load runs:**
```sql
SELECT run_id, started_at, finished_at, status, error
FROM `<project>.ops_dev.full_load_log`
ORDER BY started_at DESC
LIMIT 10;
```

**Workflow executions:**
```bash
gcloud workflows executions list poc-micro-batch-dev --location=us-central1 --limit=10
gcloud workflows executions describe <execution-id> --workflow=poc-micro-batch-dev --location=us-central1
```

---

### 7.2 Publish Logs

**Recent publishes:**
```sql
SELECT run_id, invocation_id, published_at, 
       ARRAY_LENGTH(tables) AS table_count
FROM `<project>.ops_dev.publish_log`
ORDER BY published_at DESC
LIMIT 10;
```

**Check if publish happened:**
```sql
SELECT MAX(published_at) AS last_publish,
       TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(published_at), MINUTE) AS minutes_ago
FROM `<project>.ops_dev.publish_log`;
```

---

### 7.3 Freshness Results

**Recent checks:**
```sql
SELECT entity, age_minutes, promise_minutes, breached, checked_at
FROM `<project>.ops_dev.freshness_result`
ORDER BY checked_at DESC
LIMIT 20;
```

**Current breaches:**
```sql
SELECT entity, age_minutes, promise_minutes, 
       age_minutes - promise_minutes AS minutes_late
FROM `<project>.ops_dev.freshness_result`
WHERE breached
  AND checked_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
ORDER BY age_minutes DESC;
```

---

### 7.4 DQ39 Drift Results

**Recent comparisons:**
```sql
SELECT entity, incremental_only, full_refresh_only, total_diff, checked_at
FROM `<project>.ops_dev.dq_result`
WHERE check_id = 'DQ39'
ORDER BY checked_at DESC
LIMIT 10;
```

**Any non-zero diffs:**
```sql
SELECT entity, total_diff, checked_at
FROM `<project>.ops_dev.dq_result`
WHERE check_id = 'DQ39'
  AND total_diff > 0
ORDER BY checked_at DESC;
```

---

### 7.5 Alert Emails

**Monitoring alert policies send emails to the team for:**
1. A failed `poc-*` workflow execution (this includes a full load that ends with DQ39 drift, exit code 3)
2. Freshness breaches (`freshness_breach` log event)
3. Watchdog stale (`watchdog_stale` log event)
4. CRM guard tripped (`crm_guard_tripped` log event)

There is no separate DQ39 policy: drift fails the full-load workflow, which is policy 1.
Emails go to `alert_email` (`terraform/shared/terraform.tfvars`); while it is empty the policies exist but notify nobody.

**Check in Cloud Logging:**
```bash
gcloud logging read 'severity=ERROR AND (
  jsonPayload.event="freshness_breach" OR
  jsonPayload.event="watchdog_stale" OR
  jsonPayload.event="crm_guard_tripped" OR
  jsonPayload.event="dq39_drift"
)' --limit=20 --format=json
```

---

### 7.6 dbt Artifacts

**After each run, `entrypoint.sh` (E3, not written yet) copies the dbt artifacts to GCS:**
```bash
# List recent runs
gsutil ls gs://<project>-dbt-artifacts/dev/

# Download a run's artifacts
gsutil -m cp -r gs://<project>-dbt-artifacts/dev/<run-id>/ /tmp/

# Check which models ran
cat /tmp/<run-id>/run_results.json | jq '.results[] | {node: .unique_id, status: .status, duration: .execution_time}'
```

**Files per run:**
- `run_results.json` - Which models ran, status, timing
- `manifest.json` - Full project structure and compiled SQL

---

### 7.7 BigQuery Jobs History

**Find recent jobs:**
```sql
SELECT job_id, user_email, statement_type, 
       start_time, end_time, 
       TIMESTAMP_DIFF(end_time, start_time, SECOND) AS duration_sec,
       total_bytes_billed, error_result.reason AS error
FROM `region-us-central1`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
ORDER BY creation_time DESC
LIMIT 20;
```

**Jobs by a service account:**
```sql
SELECT job_id, statement_type, start_time, error_result.reason
FROM `region-us-central1`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE user_email = 'sa-dwh-writer-dev@<project>.iam.gserviceaccount.com'
  AND creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR)
ORDER BY creation_time DESC;
```

---

### 7.8 Datastream Replication Lag

**Check the stream status:**
```bash
gcloud datastream streams describe poc-cdc-stream --location=us-central1
```

**Check replication lag in Cloud SQL:**
```sql
-- Connect to Cloud SQL as postgres user
SELECT slot_name, active, restart_lsn, confirmed_flush_lsn
FROM pg_replication_slots
WHERE slot_name = 'poc_slot';
```

**If the slot is inactive for more than 1 hour while Cloud SQL is running,** the write-ahead log grows and the disk fills. Pause the stream before stopping Cloud SQL (see section 2.1).

---

## Common Issues

| Symptom | Likely Cause | Check | Fix |
|---------|--------------|-------|-----|
| Micro-batch fails at `build_publish` | dbt test failed | `ops_dev.pipeline_run_steps` | Check DQ tables: `select * from dq_dev.<test>` |
| Freshness breach email | Simulator or Datastream paused | `ops_dev.freshness_result` | Resume (section 2.2) |
| Publish skipped | dbt didn't exit 0 | `ops_dev.pipeline_run_steps`, `publish_log` | Re-run micro-batch |
| DQ39 non-zero | Incremental logic missed data | `ops_dev.dq_result` | Check incremental model logic |
| CRM guard email | >50% of rows changed | `raw_crm.load_log` | Approve or reject (section 3) |
| Cloud SQL disk full | Replication slot lag | `pg_replication_slots` | Pause stream before stopping SQL |

---

## Emergency Contacts

| Role | Person | Email | Responsible For |
|------|--------|-------|-----------------|
| Coordinator | Dev 5 | _(fill in)_ | Gates, PO contact, questions |
| Infrastructure | Dev 4 | _(fill in)_ | Terraform, workflows, Cloud SQL, teardown |
| Security | Dev 2 | _(fill in)_ | Row policies, identities, Datastream, night-off |
| Data Pipeline | Dev 3 | _(fill in)_ | Simulator, CRM loader, incremental models |
| dbt Models | Dev 1 | _(fill in)_ | dbt models, tests, parity, physical design |

---

## References

- **Detailed Plan:** `docs/GKS-POC-Phase2-detailed-plan.md`
- **POC E Execution Plan:** `docs/poc2/poc-e-execution-plan.md`
- **Security Report:** `docs/poc2/security-report.md` (to be written)
- **Benchmark Results:** `docs/poc2/benchmark-results.md` (to be written)
- **Cost Model:** `docs/poc2/cost-model.md` (to be written)
- **dbt Docs:** `https://storage.cloud.google.com/<project>-dbt-docs/dev/index.html`

---

**End of Runbook**
