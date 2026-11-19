# POC E: Run like production. Execution plan

|               |                                                                                                    |
| ------------- | -------------------------------------------------------------------------------------------------- |
| **Source**    | `GKS-POC-Phase2-detailed-plan.md`, section 10, with sections 3, 12, 13, 15–19                      |
| **Owners**    | Dev 4 (lead, E1–E7, E9–E13). Dev 2 (E8; E12 with Dev 4)                                            |
| **Days**      | 3–12                                                                                               |
| **Status**    | Not started                                                                                        |

This document turns POC E into an ordered set of steps. The detailed plan stays the authority: if the two
disagree, the plan wins and this file is corrected.

## Contents

1. [Goal and end state](#1-goal-and-end-state)
2. [What POC E needs from others](#2-what-poc-e-needs-from-others)
3. [Timeline](#3-timeline)
4. [Step-by-step execution](#4-step-by-step-execution)
5. [Acceptance tests](#5-acceptance-tests)
6. [Gate checklist](#6-gate-checklist)
7. [Daily operations and budget](#7-daily-operations-and-budget)
8. [Risks and fallbacks](#8-risks-and-fallbacks)
9. [Open decisions](#9-open-decisions)
10. [If time runs short](#10-if-time-runs-short)

---

## 1. Goal and end state

**Goal:** the pipeline runs by itself, never publishes half-built data, keeps its freshness promises, deploys only
through CI, and builds two environments from the same code.

**End state, Day 12:**

- `dev` publishes every 15 minutes and `int` every hour, from the same commit.
- A failed build publishes nothing. Readers keep the last good version.
- A stale source raises an alert email within 15 minutes.
- Every pull request is checked before it can merge, and every merge deploys with no manual step.
- `int` can be destroyed and rebuilt from code with no console step.

**How the pieces fit:**

```
pull request ──► cloudbuild/pr.yaml (E1) ──► blocked or mergeable
merge to main ──► cloudbuild/main.yaml (E2) ──► images pushed, Terraform applied (shared, dev, int)

Cloud Scheduler ──► poc-micro-batch-{env} workflow (E4)
                      ├─ poc-crm-loader job (POC B)
                      ├─ poc-dbt-runner-{env} job (E3): dbt build ──► build_{env}
                      │                                 publish.py (E5) ──► wh_{env}, sec_{env}   (one transaction)
                      └─ freshness_check (E7) ──► ops_{env}.freshness_result ──► log-based alert ──► email

poc-watchdog (E7), every 5 min ──► stale heartbeat or case events ──► alert email
poc-full-load-{env} (E6), nightly ──► full rebuild, DQ39 drift check, publish --all
poc-night-off / poc-morning-on (E8) ──► pause and resume everything, stop and start Cloud SQL
```

---

## 2. What POC E needs from others

Check these before starting the task that needs them. If one slips, tell Dev 5 at the next stand-up.

| Needed by | Input                                                     | Task  | Owner             | Due   |
| --------- | --------------------------------------------------------- | ----- | ----------------- | ----- |
| E1, E2    | Terraform skeleton: `terraform/shared`, `terraform/env`    | 0.2   | Dev 4             | Day 2 |
| E1, E3    | dbt skeleton with targets `local`, `ci`, `dev`, `int`      | 0.4   | Dev 1             | Day 2 |
| E5        | Spike answers 1, 2, 5 and 6 in `docs/poc2/spikes.md`       | 0.9   | Dev 2, Dev 1, Dev 4 | Day 2 |
| E1        | CI check for model tests and descriptions                  | C1    | Dev 1             | Day 3 |
| E1        | Single-definition-of-customer check                        | B8    | Dev 5             | Day 6 |
| E4        | CRM loader job `poc-crm-loader`                            | B3    | Dev 3             | Day 5 |
| E7, E8    | Simulator running in the cloud, with heartbeat             | A8    | Dev 3 (code), Dev 4 (Terraform) | Day 6 |
| E8        | Cloud SQL `poc-ops-db` and Datastream `poc-cdc-stream`     | A1, A4 | Dev 2            | Day 4 |
| E5        | Row policy SQL in `orchestration/publish/policies/`        | D4    | Dev 2             | Day 7 |
| E5        | `tables.yaml` entries and native views in `objects/`       | C11   | Dev 1             | Day 9 |
| E7        | `crm_guard_tripped` log event from the loader              | B5    | Dev 3             | Day 7 |
| E9, E12   | Security suite tenant cases                                | D5    | Dev 2             | Day 8 |

---

## 3. Timeline

| Day | Dev 4                                  | Dev 2       | Milestone                                                    |
| --- | -------------------------------------- | ----------- | ------------------------------------------------------------ |
| 3   | E1                                     |             |                                                              |
| 4   | E1                                     |             |                                                              |
| 5   | E1, E3                                 | E8          |                                                              |
| 6   | E2, E3                                 | E8          | **G6:** AT-36 passes; E8 each run by hand once               |
| 7   | E4, E5, E7                             |             |                                                              |
| 8   | E4, E5, E7                             |             |                                                              |
| 9   | E6, E7, E11, E9                        |             | Start the 24-hour run (AT-32 part 1) in the afternoon        |
| 10  | E9, E10                                |             | **G7:** AT-29 passes; 24-hour run finished                   |
| 11  | E12, E13                               | E12         |                                                              |
| 12  | E13, teardown                          | teardown    | **G8:** AT-31, AT-32, AT-35, AT-37 pass; teardown done       |

Dev 4 also owns these tasks outside POC E in the same days, so plan around them: 0.2, 0.8, A6 (Days 3–4),
A8 Terraform (Days 5–6), C10 `fct_case` and `dim_offender` (Day 8), C12 (Day 7), and the daily cost check.

---

## 4. Step-by-step execution

Each task follows the same shape: what it is, the steps, the files, how to check it is done, and what to watch out
for. One branch and pull request per task: `p2/<task-id>-<short-name>`.

### E1. CI on pull requests (Dev 4, Days 3–5)

**What:** a Cloud Build check on every pull request to `main`. A failing check blocks the merge.

**Steps:**

1. Create `cloudbuild/pr.yaml`.
2. **Terraform stage,** for each of `shared`, `env` with `dev`, `env` with `int`:
   ```
   terraform fmt -check -recursive
   terraform init -backend-config=<env>.backend.hcl
   terraform validate
   terraform plan -var-file=<env>.tfvars -out=plan.out
   terraform show -no-color plan.out | grep '^Plan:'     # one-line summary per plan
   ```
3. **Python stage:** `pytest loaders/ orchestration/publish/ apps/ scripts/`.
4. **dbt stage:**
   1. Create the `dbt_pr_<number>_*` datasets with a one-day default table expiration.
   2. `dbt deps`, then `dbt build --target ci`. Sources are the shared landing datasets, read-only.
5. **Rule checks** (scripts in `scripts/ci/`):
   - every `build` model has `unique` and `not_null` tests on its key and a description on every column (C1, Dev 1);
   - one definition of customer (B8, Dev 5);
   - between environments, only `*.tfvars` and `*.backend.hcl` differ (`check_env_diff.py`, Dev 4).
6. Create the Cloud Build trigger on pull requests to `main`, in Terraform.
7. Grant the Cloud Build service account: Terraform plan rights in the sandbox, editor on `dbt_pr_*`, job user.
8. In GitHub branch protection on `main`, make the trigger a required check.

**Done when:** AT-36 passes (section 5).

**Watch out:**

- Start with the Terraform and Python stages; they work before any dbt model exists.
- Missing IAM on the Cloud Build service account is the most likely first failure.
- CI only plans. It never applies.

### E3. dbt runner image and Cloud Run job (Dev 4, Days 5–6)

**What:** one container that runs dbt and, after it, `publish.py`, so publish only ever sees the build it follows.

**Steps:**

1. `dbt/Dockerfile`: from `python:3.12-slim`, install `dbt/requirements.txt`, copy `dbt/` and
   `orchestration/publish/`, run `dbt deps` at build time.
2. `dbt/entrypoint.sh` with three commands:
   | Command       | Runs                                                                         |
   | ------------- | ---------------------------------------------------------------------------- |
   | `microbatch`  | `dbt build --exclude tag:daily`; then `publish.py` only if dbt exited 0     |
   | `fullload`    | The daily full load (E6)                                                     |
   | `dbt <args>`  | Pass-through to dbt                                                          |
3. After each run, copy `target/run_results.json` and `target/manifest.json` to
   `gs://data-lake-poc-512405-dbt-artifacts/<env>/<run_id>/`.
4. Terraform, module `run_jobs`: Cloud Run job `poc-dbt-runner-{env}`.
   - Service account `sa-dwh-writer-{env}`.
   - Environment variable `DBT_TARGET={env}`.
   - Timeout 15 minutes, `max_retries = 0`. The workflow decides what to do on failure.
   - Image tag: the commit SHA, so every run can be traced to its code.
5. Build and push the image once by hand to test; from E2 onwards CD does it.
6. Run it: `gcloud run jobs execute poc-dbt-runner-dev --region us-central1 --args=dbt,build --wait`.

**Done when:** the job runs `dbt build` in the cloud.

### E2. CD on merge (Dev 4, Day 6)

**What:** every merge to `main` deploys with no manual step.

**Steps:**

1. Create `cloudbuild/main.yaml`, in this order:
   1. Build and push the dbt runner image, tagged with the commit SHA.
   2. Build and push the `poc-crm-loader` image.
   3. `terraform apply` for `shared`, then `dev`. Add `int` from Day 9 (E9).
   4. From Day 10: `dbt docs generate --static` and copy to the docs bucket (E10).
2. Images first, then Terraform, so the jobs point at an image that already exists.
3. Create the trigger on pushes to `main`, in Terraform.
4. Before applying `shared`, Dev 2 reviews the plan (Dev 4 reviews Dev 2's own changes).

**Done when:** a merge deploys with no manual step.

### E8. Night-off and morning-on (Dev 2, Dev 4 reviews, Days 5–6)

**What:** two workflows that stop the pipeline in the evening and start it in the morning, to save cost.

**Steps:**

1. `orchestration/night_off.workflow.yaml`, `poc-night-off`, 20:00 Monday to Friday, team's time zone. In this
   order:
   1. Pause the scheduler jobs: simulator, micro-batch `dev` and `int`, watchdog
      (`googleapis.cloudscheduler.v1.projects.locations.jobs.pause`).
   2. Pause the Datastream stream (`googleapis.datastream.v1.projects.locations.streams.patch`, state `PAUSED`).
   3. Stop Cloud SQL (`googleapis.sqladmin.v1.instances.patch`, `activationPolicy = NEVER`).
2. `orchestration/morning_on.workflow.yaml`, `poc-morning-on`, 08:00 Monday to Friday:
   1. Start Cloud SQL (`activationPolicy = ALWAYS`) and wait until it is `RUNNABLE`.
   2. Resume the stream.
   3. Resume the simulator.
   4. Wait 5 minutes, then resume the micro-batch and watchdog jobs, so the first freshness check sees new data.
3. Terraform: the two workflows and their scheduler jobs, run as `sa-orchestrator` with the Cloud SQL, Datastream
   and Scheduler rights they need.
4. Add `ignore_changes` so Terraform doesn't undo what the workflows do:
   - Datastream stream: `desired_state`;
   - scheduler jobs: `paused`;
   - Cloud SQL: `settings[0].activation_policy`.
5. Run each workflow by hand once. Check no data is lost: after morning-on, the change rows made just before
   night-off are in `raw_g2`.
6. Schedule them.

**Done when:** each run by hand once by Day 6, with no errors and no data lost; then scheduled.

**Watch out:** never leave the stream paused with the database running for more than an hour. The replication slot
keeps write-ahead log and the disk fills. That is why the stream pauses before the database stops.

### E5. `publish.py`: write-audit-publish (Dev 4, Days 7–8)

**What:** copies the tested build from `build_{env}` into `wh_{env}` (and `map_tenant_access` into `sec_{env}`)
in one transaction. Readers see the old version of every table or the new one, never a mix.

**Rules (D-27, D-28):** dbt never writes to `wh_{env}`. `publish.py` owns everything in it: tables, row policies,
native materialized views, table options. Published tables are never recreated.

**Before starting:** read the spike answers. If spike 2 or 6 said "no", the design below changes first.

| Spike | Question                                                                     | If "no"                                                    |
| ----- | ---------------------------------------------------------------------------- | ---------------------------------------------------------- |
| 2     | DELETE and INSERT in one transaction on a table with row policies and `require_partition_filter` | Redesign before Day 6                 |
| 5     | Does `CREATE TABLE ... LIKE` copy partitioning, clustering and the filter?   | `publish.py` sets the missing options itself               |
| 6     | One transaction over about 20 tables: limits and time                        | Two transactions: dimensions with facts, then marts         |

**Steps:**

1. **Config:** `orchestration/publish/config.dev.yaml` (project, datasets, environment) and read `tables.yaml`
   (table type: dimension, fact, mart or security; partition column for facts).
2. **Step 1, gate:** if dbt didn't exit 0, log `PUBLISH_SKIPPED` and stop.
3. **Step 2, changed partitions:** for each fact,
   `SELECT DISTINCT <partition_column> FROM build_{env}.<fact> WHERE _dbt_invocation_id = @invocation_id`.
4. **Step 3, set-up outside the transaction** (DDL can't be in a transaction). All idempotent:
   - `CREATE TABLE IF NOT EXISTS wh.<t> LIKE build.<t>`;
   - `require_partition_filter` on facts;
   - `ADD COLUMN` for new columns. A removed or retyped column stops the publish with a clear message;
   - row policies from `policies/*.sql` (D4);
   - native materialized views from `objects/*.sql` (C11).
5. **Step 4, one transaction:** generated SQL with explicit column lists from `INFORMATION_SCHEMA.COLUMNS`:
   - dimensions, marts and `map_tenant_access`: `DELETE ... WHERE TRUE`, then `INSERT ... SELECT`;
   - facts: delete and insert only the changed partitions;
   - insert a row into `ops_{env}.publish_log`;
   - `COMMIT`, or `ROLLBACK` and `RAISE` on any error.
   The SQL template is in the plan, task E5.
6. **Step 5, checks:**
   - row counts in `wh` equal `build` for dimensions, marts and the changed fact partitions;
   - both row policies exist on every tenant-scoped table (`rowAccessPolicies.list`).
   A failed check exits non-zero, so the workflow fails and the alert fires.
7. **`--all` mode** for E6: publish every partition.
8. **Tests** in `orchestration/publish/tests/`: SQL generation, the skip path, the column-change stop.
9. Wire into `entrypoint.sh microbatch`. Run by hand in `dev`.

**Done when:** AT-29 passes (proved by E11).

### E4. Micro-batch workflow (Dev 4, Days 7–8)

**What:** the workflow that runs one pipeline cycle. Reuse the `log_step` pattern and error handling from
`workflow-data-lake-poc/workflow.yaml`.

**Steps:**

1. `orchestration/micro_batch.workflow.yaml`:
   | Step            | What it does                                                                                     |
   | --------------- | ------------------------------------------------------------------------------------------------ |
   | `init`          | `run_id`, env, project; `run_crm_loader` from the workflow's variables                           |
   | `single_run`    | If another execution of this workflow is active: log `SKIPPED` and return                        |
   | `load_crm`      | If `run_crm_loader`: run `poc-crm-loader` and wait                                               |
   | `freshness_src` | dbt job with `[dbt, source, freshness, --target, env]`. Warn only                                |
   | `build_publish` | dbt job with `[microbatch]`. Fails the workflow if dbt or publish fails                          |
   | `freshness`     | dbt job with `[dbt, run-operation, freshness_check, --target, env]`                              |
   | logging         | After **every** step, `log_step` into `ops_{env}.pipeline_run_steps` with status and error       |
2. Run Cloud Run jobs with `googleapis.run.v2.projects.locations.jobs.run`, passing the arguments as container
   overrides.
3. Terraform, module `workflows`: the workflow and its scheduler, `*/15 * * * *` in `dev`, `0 * * * *` in `int`,
   as `sa-orchestrator`.
4. Measure run time. Keep it under 4 minutes. If it grows, tag the alert-path models `hot`, run only `tag:hot` every
   15 minutes and everything else hourly.

**Done when:** it runs every 15 minutes for a day, and every run is logged.

### E7. Freshness, watchdog and alerts (Dev 4, Days 7–9)

**What:** each data type has a freshness promise. A broken promise, or a stopped source, sends an email.

**Steps:**

1. **Seed `dbt/seeds/entity_registry.csv`:**
   | entity          | measured_on               | ts_column            | sync_mode | promise (min) | checked by  | owner |
   | --------------- | ------------------------- | -------------------- | --------- | ------------- | ----------- | ----- |
   | `alert`         | `wh.fct_alert`            | `_source_updated_at` | cdc       | 20            | micro-batch | Dev 3 |
   | `alert_history` | `wh.fct_alert_history`    | `_source_updated_at` | cdc       | 20            | micro-batch | Dev 3 |
   | `case_raw`      | `raw_lpos.case_event`     | `publish_time`       | stream    | 5             | micro-batch | Dev 4 |
   | `case`          | `wh.fct_case`             | `_source_updated_at` | stream    | 20            | micro-batch | Dev 4 |
   | `crm_export`    | `raw_crm.account_landing` | `export_ts`          | batch     | 75            | micro-batch | Dev 3 |
   | `wheel_event`   | `wh.fct_wheel_event`      | `_source_updated_at` | batch     | 30            | micro-batch | Dev 1 |
   | `heartbeat`     | `raw_g2.g2_heartbeat`     | source timestamp     | cdc       | 8             | watchdog    | Dev 4 |
2. **Macro `dbt/macros/freshness_check.sql`** (run-operation): for each entity, age = now minus newest
   `ts_column`. Write a row to `ops_{env}.freshness_result`. For each breach, print a JSON log line with
   `severity: ERROR` and `event: freshness_breach`.
3. **Source freshness (C12):** the same values in each `sources_<system>.yml`.
4. **Watchdog** `orchestration/watchdog.workflow.yaml`, `poc-watchdog`, every 5 minutes. One cheap query: age of
   the newest `simulator` heartbeat in `raw_g2.g2_heartbeat`, and of the newest `raw_lpos.case_event` row (filtered
   to the last day). Older than 8 minutes: log `event: watchdog_stale` at `ERROR`.
5. **Monitoring module:** an email channel to the team, and four alert policies:
   1. failed executions of any `poc-*` workflow;
   2. log-based metric on `freshness_breach`;
   3. log-based metric on `watchdog_stale`;
   4. log-based metric on `crm_guard_tripped` (B5).
6. Test each policy once by forcing its condition.

**Done when:** AT-32 passes.

### E6. Daily full load (Dev 4, Day 9)

**What:** a nightly full rebuild that checks the incremental logic hasn't drifted.

**Steps:**

1. `orchestration/full_load.workflow.yaml`, `poc-full-load-{env}`, 20:15 Monday to Friday, after night-off. It
   reads only BigQuery, so Cloud SQL can be stopped.
2. `entrypoint.sh fullload`:
   1. Clone every incremental fact: `CREATE OR REPLACE TABLE ops_{env}.prev_<fact> CLONE build_{env}.<fact>`.
   2. `dbt build --full-refresh`.
   3. **DQ39:** compare each fact with its clone, both ways (`EXCEPT DISTINCT` each direction). Write the count of
      differing rows to `ops_{env}.dq_result`.
   4. `publish.py --all`.
   5. Scan `build` for personal data (C9).
3. Any DQ39 difference is an error to explain: the incremental logic missed something. Raise it with Dev 3.

**Done when:** it runs nightly and drift is recorded.

### E11. Forced-failure test (Dev 4, Day 9)

**What:** proves a failure mid-build leaves `wh_dev` untouched.

**Steps:**

1. Add a singular test `dbt/tests/force_fail_mv_store_health.sql` that fails only when `var('force_fail')` is true.
   `mv_store_health` is in the middle of the graph, so some `build` tables have already changed when it fails.
2. Record a fingerprint of every `wh_dev` table, with a partition filter covering every date on facts:
   ```sql
   SELECT BIT_XOR(FARM_FINGERPRINT(TO_JSON_STRING(t))) FROM wh_dev.<table> AS t
   ```
3. Run a micro-batch with `--vars '{force_fail: true}'`.
4. Check:
   - the workflow failed and the alert email arrived;
   - every `wh_dev` fingerprint is unchanged;
   - both policies are still on every tenant-scoped table.
5. Run a normal micro-batch and check it publishes.
6. Save the evidence (fingerprints before and after, the email, the run log) for the gate.

**Done when:** AT-29 passes.

### E9. Second environment, `int` (Dev 4, Days 9–10)

**Steps:**

1. Write `terraform/env/int.tfvars` and `int.backend.hcl`. Nothing else differs from `dev`.
2. Add `int` to `cloudbuild/main.yaml`: `terraform apply -var-file=int.tfvars` with `int.backend.hcl`, on the same
   commit as `dev`.
3. This creates the `*_int` datasets, `sa-dwh-writer-int`, the `int` jobs, workflows, hourly schedulers and
   monitoring.
4. Add the dbt target `int` and `orchestration/publish/config.int.yaml`.
5. Run one `int` micro-batch, then the security suite's tenant cases against `int`.

**Done when:** AT-31 passes.

### E10. Lineage and docs (Dev 4, Day 10)

**Steps:**

1. Turn on the Data Lineage API in Terraform (`google_project_service`). BigQuery jobs then record lineage.
2. In the console, check the lineage of `wh_dev.fct_alert` shows `raw_g2` to `build_dev` to `wh_dev`. Lineage is
   between tables, not columns.
3. Add to `cloudbuild/main.yaml`: `dbt docs generate --static`, then copy the single HTML file to
   `gs://data-lake-poc-512405-dbt-docs/<env>/index.html`.
4. Open it through the authenticated Cloud Storage link and check every model has a description.

**Done when:** AT-37 passes.

### E12. Terraform destroy and re-apply (Dev 4 with Dev 2, Day 11)

**Steps:**

1. Write down the current state: a list of `int` resources and a green `int` micro-batch.
2. `terraform destroy` the `int` environment.
3. Re-apply from CI (a merge or a manual trigger run), not from a laptop.
4. Run one `int` micro-batch and the security suite's tenant cases. Both must be green with no console step.
5. Run `terraform plan` for `shared`. It must show no changes.
6. If any step needed the console, fix the Terraform and repeat.
7. Put the one-time steps in the runbook: state bucket, `g2_bootstrap.py`, `load_token_key.py`, the second
   project, Looker Studio.

**Done when:** AT-35 passes.

### E13. Runbook (Dev 4, Days 11–12)

**What:** `docs/poc2/runbook.md`, for someone who didn't build the system.

**Sections:**

1. One-time setup: the state bucket command and the steps from E12.
2. Pause and resume: by hand, and through night-off and morning-on.
3. Approve a held CRM export (the B5 guard).
4. Re-run a failed micro-batch or full load.
5. Reservations: create and destroy (F4).
6. Teardown (section 7).
7. Where to look: run log, publish log, freshness results, alert emails, dbt artifacts.

**Done when:** another developer follows it without help. Ask one to try it on Day 12.

---

## 5. Acceptance tests

| Test  | What it proves                       | How to run it                                                                                                       | Passes when                                                                                       | Gate |
| ----- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ---- |
| AT-36 | CI blocks bad changes                | Open four pull requests: a failing dbt test, a Terraform format error, a failing pytest, then a clean one           | The first three are blocked; the clean one passes                                                 | G6   |
| AT-29 | Never half-published                 | E11, and D5 case 7                                                                                                  | `wh` fingerprints unchanged; alert sent; policies still in place                                  | G7   |
| AT-32 | Freshness promises hold, and breaches alert | (1) 24 hours of continuous running from the afternoon of Day 9, night-off switched off for that night. (2) Pause the simulator's scheduler job. (3) Pause the Datastream stream | (1) No breach in `freshness_result`, or each one explained. (2) and (3) Alert email within 15 minutes; recovers after resume | G8 |
| AT-31 | Two environments from one commit     | E9                                                                                                                  | Only `*.tfvars` and `*.backend.hcl` differ; `int` micro-batch green; tenant cases green in `int`  | G8   |
| AT-35 | Rebuild from code                    | E12                                                                                                                 | `int` destroyed and re-applied with no console step; `shared` plan shows no changes               | G8   |
| AT-37 | Lineage and docs                     | E10                                                                                                                 | Lineage for `wh_dev.fct_alert` shows `raw_g2` to `build_dev` to `wh_dev`; docs page opens with every model described | G8 |

Data-quality checks POC E runs: **DQ39** (incremental vs full rebuild, E6, target 0) and **DQ40** (no CRM export in
75 minutes, raised by `freshness_check`, owned by Dev 3).

Put each test as `scripts/acceptance/at<nn>_<name>.py` so `run_all.py` can re-run it before G8.

---

## 6. Gate checklist

Items marked **(plan)** are the plan's gate criteria that involve POC E or its dependencies. Items marked
**(extra)** are added here as POC E readiness checks. They don't block the gate in the plan, so the team decides
whether to enforce them.

**G5, Day 2**

- [ ] **(plan)** Terraform and dbt skeletons merged, with CI planning for `shared`, `dev` and `int` (0.2, 0.4)
- [ ] **(plan)** Spikes answered (0.9), including spike 6 (Dev 4)
- [ ] **(plan)** Budget alerts live (0.8)
- [ ] **(plan)** Decisions marked "Confirm at G5" confirmed or changed, including D-26 and D-28

**G6, Day 6**

- [ ] **(plan)** AT-36 passes
- [ ] **(plan)** Night-off and morning-on each run by hand once, cleanly (E8)
- [ ] **(extra)** The dbt runner job runs `dbt build` in the cloud (E3)
- [ ] **(extra)** A merge to `main` deploys with no manual step (E2)

**G7, Day 10**

- [ ] **(plan)** AT-29 passes
- [ ] **(plan)** The 24-hour continuous run (AT-32, part 1) has finished
- [ ] **(extra)** Micro-batch has run every 15 minutes for a day with every run logged (E4)
- [ ] **(extra)** Full load runs nightly and DQ39 is recorded (E6)

**G8, Day 12**

- [ ] **(plan)** AT-31, AT-32, AT-35 and AT-37 pass
- [ ] **(plan)** Every earlier test still passes (`run_all.py`)
- [ ] **(plan)** Reservations destroyed
- [ ] **(plan)** Teardown done per the runbook
- [ ] **(plan)** Knowledge-sharing demo of POC E and its trade-offs
- [ ] **(extra)** Runbook followed by another developer without help (E13)

---

## 7. Daily operations and budget

**Every morning (Dev 4):**

1. Billing report filtered on label `poc=phase2`. Total so far against the 80 USD ceiling.
2. Overnight: did night-off, the full load and morning-on succeed? Any DQ39 difference?
3. `ops_dev.freshness_result` and `ops_dev.pipeline_run_steps`: any breaches or failed runs?
4. Replication slot lag (with Dev 2).

**Cost controls POC E owns:** 15 minutes only in `dev`, hourly in `int`; incremental models; Cloud Run, Workflows,
Scheduler and Pub/Sub paused at night.

**If the 60 USD alert fires:** switch `dev` to hourly (the D-26 fallback) and pause the simulator outside test
windows. Agree with the team what else to stop.

**Teardown, Day 12, by the runbook:** check both reservations are gone, delete `scale`, pause every scheduler job,
stop Cloud SQL. The team agrees what to keep; Dev 5 tells the PO.

---

## 8. Risks and fallbacks

| Risk                                                             | Effect                              | What we do                                                              | Owner |
| ---------------------------------------------------------------- | ----------------------------------- | ----------------------------------------------------------------------- | ----- |
| Spike 2 or 6 fails: the one-transaction publish doesn't work     | E5 redesign                         | Decide by Day 6; two transactions is the documented fallback            | Dev 4 |
| A micro-batch takes more than 4 minutes                          | The 20-minute promise breaks        | Run only `tag:hot` every 15 minutes, everything else hourly             | Dev 4 |
| Write-ahead log fills the disk while the stream is paused        | Cloud SQL stops                     | Night-off order; check slot lag daily                                   | Dev 2 |
| A8 or B3 slips                                                   | E4, E7 and the 24-hour run slip     | Raise at the stand-up; test E4 with the loader step switched off        | Dev 4 |
| The 24-hour run starts late                                      | AT-32 not ready for G7              | Start on Day 9 afternoon at the latest; switch night-off off that night | Dev 4 |
| Terraform reverts what night-off changed                         | Things start at night, cost rises   | `ignore_changes` on the three fields in E8                              | Dev 2 |
| Destroying `int` touches shared resources                        | `dev` breaks                        | Shared resources live only in `terraform/shared`; destroy only `env` with `int` state | Dev 4 |
| Spend runs ahead of plan                                         | The POC stops early                 | Section 7                                                               | Dev 4 |

---

## 9. Open decisions

Confirmed by Dev 5 with the PO at G5. If an answer changes, these tasks change.

| Decision | Choice in the plan                                                                 | Affects       |
| -------- | ---------------------------------------------------------------------------------- | ------------- |
| D-26     | dbt as a Cloud Run job started by Workflows; 15 minutes in `dev`, hourly in `int`; daily full rebuild | E3, E4 |
| D-27     | Write-audit-publish: build in `build_{env}`, publish in one transaction (approved)  | E5            |
| D-28     | The publish step owns everything in `wh_{env}`                                     | E5, D4, C11   |
| D-22     | `dev` and `int` share the sandbox project                                          | E9            |

---

## 10. If time runs short

From the plan's cut order, the item that touches POC E is number 3: **the `int` schedule**. Build `int` once from CI
instead of hourly; AT-31 still holds.

**Never cut:** write-audit-publish, the freshness alerts and the budget controls.
