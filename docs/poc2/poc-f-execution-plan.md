# POC F: Performance and cost. Execution plan

|               |                                                                                                              |
| ------------- | ------------------------------------------------------------------------------------------------------------ |
| **Source**    | `GKS-POC-Phase2-detailed-plan.md`, section 11, with sections 3, 4, 8 (C10, C11), 9 (D4, D10), 12, 14–19       |
| **Owners**    | Dev 1 (lead: F2, F3, F4, F6, F7, F8). Dev 5 (F1, F5, F6, F8, F9 stretch)                                      |
| **Helpers**   | Dev 2 (tenant-identity runs on Day 11, D10), Dev 3 (helps F2, Days 10–11), Dev 4 (reviews F4, daily cost check) |
| **Days**      | 7–12                                                                                                         |
| **Status**    | Not started                                                                                                  |

This document turns POC F into an ordered set of steps. The detailed plan stays the authority: if the two
disagree, the plan wins and this file is corrected. Points this file adds that the plan doesn't state are marked
**(added)**. They are suggestions; the team decides at the next gate whether to keep them.

## Contents

1. [Goal and end state](#1-goal-and-end-state)
2. [What POC F needs from others](#2-what-poc-f-needs-from-others)
3. [Timeline](#3-timeline)
4. [Step-by-step execution](#4-step-by-step-execution)
5. [Benchmark days run sheet (Days 11–12)](#5-benchmark-days-run-sheet-days-1112)
6. [Acceptance tests](#6-acceptance-tests)
7. [Gate checklist](#7-gate-checklist)
8. [Budget and teardown](#8-budget-and-teardown)
9. [Risks and fallbacks](#9-risks-and-fallbacks)
10. [Open decisions and gaps found while planning](#10-open-decisions-and-gaps-found-while-planning)
11. [If time runs short](#11-if-time-runs-short)

---

## 1. Goal and end state

**Goal:** measure how fast the real questions are at scale, under each pricing set-up, with and without security,
and work out the monthly cost and the break-even point. The figures come from a generated workload: they show
_how_ to decide, not GKS's real bill.

**End state, Day 12:**

- `scale` holds about 50 million rows in `fct_alert_history`, with the same schema, partitioning, clustering and
  row policies as `wh`.
- `ops_dev.benchmark_result` has 10 runs for every query in every cell of the matrix (section 5).
- `docs/poc2/benchmark-results.md` gives p50 and p95 latency, bytes billed and slot time per query and set-up,
  compares the two native materialized views with their dbt tables and base facts, and says "generated workload".
- `docs/poc2/cost-model.md` gives the monthly cost of on-demand and Enterprise for scenarios S1–S3, the
  break-even point, every assumption, and the date the prices were read.
- A Looker Studio report on `wh_dev`, with viewer's credentials, shows different rows to two tenant users.
- Both reservations are destroyed and `scale` is deleted.

**How the pieces fit:**

```
F1 queries (scripts/benchmark/queries/*.sql) ──► F3 runner (scripts/benchmark/run.py)
                                                     │  impersonates: internal analyst, tenant A
                                                     │  runs each query 10× per cell, cache off, 2 GB cap
                                                     ▼
F2 scale data (scale.*) ◄── read by ── BigQuery ── under set-up: on-demand │ + BI Engine (F4) │ Enterprise (F4)
                                                     │
                                                     ▼
                         region-us-central1.INFORMATION_SCHEMA.JOBS_BY_PROJECT
                                                     │  (duration, bytes, slot ms, BI Engine mode)
                                                     ▼
                                         ops_dev.benchmark_result
                                          │                      │
                                          ▼                      ▼
                          F8 benchmark-results.md     F7 cost-model.md ◄── Day 9 micro-batch jobs
F5 Looker Studio on wh_dev (viewer's credentials) ──► AT-24 dashboard part (with D10)
```

---

## 2. What POC F needs from others

Check these before starting the task that needs them. If one slips, tell Dev 5 at the next stand-up.

| Needed by | Input                                                                                     | Task  | Owner          | Due    |
| --------- | ----------------------------------------------------------------------------------------- | ----- | -------------- | ------ |
| F4        | Terraform skeleton, with the `reservations` module wired into `terraform/shared`, off     | 0.2   | Dev 4          | Day 2  |
| F2, F6    | Spike 4: can a native materialized view sit on a table with row policies and a required partition filter, and what does a tenant see? | 0.9 | Dev 1 | Day 2 |
| F4, F6    | D-21 confirmed: reservations in `us-central1`                                             | 0.1   | Dev 5          | G5     |
| F7        | Budget alerts live, billing report filtered on `poc=phase2`                               | 0.8   | Dev 4          | Day 1  |
| F1        | The marts the POC 1 questions read: `mv_store_health`, `mv_current_issues`, `mv_downtime_interval`, `mv_alert_trend_weekly`, `fct_alert`, `fct_alert_history` | C5 | Dev 1, Dev 5 | Day 8 |
| F1        | Story tables: `fct_case`, `fct_wheel_event`, `mv_cart_count_daily`, `dim_date`            | C10   | Dev 4, Dev 1, Dev 5 | Day 8 |
| F2        | Physical design in `wh`: partitioning, clustering, the two native views                   | C11   | Dev 1          | Day 9  |
| F2, F5    | Row policy SQL in `orchestration/publish/policies/`, applied on `wh_dev`                  | D4    | Dev 2          | Day 7  |
| F3        | Impersonation pattern for test identities (`google.auth.impersonated_credentials`)        | D5    | Dev 2          | Day 8  |
| F5        | Two team members' Google accounts mapped to tenants A and B in `store_access`, and named in the tenant policy's grantee list | D3, D4 | Dev 5, Dev 2 | Day 10 |
| F7        | One normal day of micro-batch runs in `dev`                                               | E4    | Dev 4          | Day 9  |
| F6        | CD applying `terraform/shared` on merge                                                   | E2    | Dev 4          | Day 6  |

---

## 3. Timeline

From the plan's section 14.2, with helpers shown.

| Day | Dev 1                   | Dev 5           | Helpers                                   | Milestone                                                                 |
| --- | ----------------------- | --------------- | ----------------------------------------- | ------------------------------------------------------------------------- |
| 2   | Spike 4 (0.9)           |                 |                                           | **G5:** spike 4 answered                                                  |
| 7   |                         | F1              |                                           |                                                                           |
| 8   | F3                      | F1              |                                           | F1: 10 queries reviewed by Dev 1                                          |
| 9   | F3, F4                  |                 | Dev 4 reviews F4                          | Day 9 micro-batch workload recorded for F7                                |
| 10  | F2, F3, F4              |                 | Dev 3 helps F2                            | **G7:** F3 dry run works; F4 plan correct; **(added)** F2 built           |
| 11  | F2 (verify), F6         | F5, D10, F6     | Dev 2: F6 tenant runs, D10. Dev 3: F2     | BI Engine on at noon, **destroyed in the evening**                        |
| 12  | F6, F7, F8              | F6, F8          | All: teardown                             | Enterprise destroyed by noon. **G8:** AT-24 (dashboard), AT-30, AT-34     |

**Dev 1 is the most loaded developer in the plan** (C-series until Day 9, then all of F). Protect Day 10 for F2.

**Plan gap (added):** the plan gives F2 Days 10–11, but the first benchmark cell is Day 11 morning and reads
`scale`. Aim to finish F2 by the end of Day 10, with Dev 3's help, and keep Day 11's first hour for checking it.

---

## 4. Step-by-step execution

Each task follows the same shape: what it is, the steps, the files, how to check it is done, and what to watch out
for. One branch and pull request per task: `p2/<task-id>-<short-name>`.

### F1. Benchmark questions (Dev 5, Days 7–8)

**What:** the 10 questions the benchmark times, as parameterised SQL, with expected answers on `dev` data.

**Steps:**

1. The six POC 1 reader questions come from the "Which table answers which question" table in
   `data-lake-ETL-tool/docs/Store_Alert_Warehouse_Schema_Suggestion_Update.html`. Its seventh row, "Did last
   night's run work?", reads the ops tables, is admin-only, and is **not** benchmarked. Write each question as SQL
   on the story's table names (Appendix A of the detailed plan: `fk_store` becomes `store_id`,
   `fct_alert_incident` becomes `fct_alert`).
2. Write the questions:

   | #   | Question (from POC 1)                          | Reads                                   | POC 1 filter and sort                                                      | Variants |
   | --- | ---------------------------------------------- | --------------------------------------- | -------------------------------------------------------------------------- | -------- |
   | q1  | Which of my stores need attention?             | `mv_store_health`                       | Allowed stores; optional `level_1`, `brand`. RED first, then longest `status_duration_minutes` | One |
   | q2  | What is wrong at this store, door by door?     | `mv_current_issues`                     | `store_id = @store_id`. RED first, main doors first, oldest first           | One      |
   | q3  | What happened to this alert?                   | `fct_alert_history`                     | `incident_id = @incident_id`, sorted by changed date then id. **Add** an `event_date` range: `wh` requires it | One |
   | q4  | How much downtime, and when?                   | `mv_downtime_interval`                  | Allowed stores; `downtime_end >= @from`; sorted by `downtime_start`         | One      |
   | q5  | Uptime by region or brand                      | `mv_store_health`                       | Allowed stores; `GROUP BY level_1` or `brand`                              | One, with a `@group_by` choice. Run it grouped by region (keeps the total at 14 variants) |
   | q6  | Is it getting better?                          | `mv_alert_trend_weekly`, `mv_alert_trend_daily` | Allowed stores; date range; sorted by `week_start`                 | One on the weekly mart |
   | q7  | Store coverage by brand and region: customer stores against stores without a customer account | `dim_store`, `dim_account` (internal identity only)        | One                          |
   | q8  | Current cases by store                                                                    | `fct_case`                                                     | One                          |
   | q9  | Cart exit attempts by store and day, last 30 days                                         | `mv_cart_count_daily`, `fct_wheel_event`                       | `mv` (native), `tbl` (dbt), `base` |
   | q10 | Daily alert trend, last 90 days                                                           | `mv_alert_trend_daily`, `fct_alert`                            | `mv` (native), `tbl` (dbt), `base` |

   That is **14 query variants** in total.
3. **File layout:** one file per variant, `scripts/benchmark/queries/q09_mv.sql`, `q09_tbl.sql`, `q09_base.sql`,
   and so on. A header comment holds the question, the tables read, and which identities run it.
4. **Parameters:**
   - Dates, tenant and store values are BigQuery query parameters: `@as_of`, `@from_date`, `@to_date`.
   - Table and dataset names can't be query parameters. Write them as `{project}.{dataset}.<table>`; the runner
     fills in `wh_dev` or `scale`. **(added)**
   - The `tbl` variants of q9 and q10 read the dbt versions. In `wh_dev` those are in `build_dev`, so use a
     `{rollup_dataset}` placeholder too. **(added)**
5. **Every query on a fact has a date filter,** as a dashboard would. q7 is internal only, because tenants can't
   see stores without a customer account.
6. **Expected answers:** run each query on `wh_dev` as the internal analyst with fixed parameter values. Save the
   result as `scripts/benchmark/expected/<query>.csv`. q9 and q10: the three variants must give the same answer.
7. Dev 1 reviews all 14 for: a date filter on every fact, columns that match the clustering order
   (`tenant_id`, `store_id`, ...), no `SELECT *`.

**Done when:** 10 queries (14 variants) reviewed by Dev 1, expected answers saved.

**Watch out:**

- `mv_cart_count_daily` uses `APPROX_COUNT_DISTINCT(wheel_id)` because a native view doesn't allow
  `COUNT(DISTINCT)`. If the dbt table uses an exact count, `active_wheels` won't match exactly. Either make the dbt
  version use the same approximate function, or compare that column with a tolerance and say so. **(added)**
- Don't put `CURRENT_DATE()` in the SQL. Pass `@as_of`, so the results don't change between runs and days.

### F3. Benchmark runner (Dev 1, Days 8–10)

**What:** `scripts/benchmark/run.py` runs every query variant as a given identity under the current set-up, and
records each run in `ops_dev.benchmark_result`.

**Command line:**

```
python scripts/benchmark/run.py \
  --setup ondemand|bi_engine|enterprise \
  --identity internal|tenant_a \
  --dataset scale|wh_dev \
  --queries all|q01,q09_mv,... \
  --runs 10 \
  [--dry-run] [--check-expected]
```

**Steps:**

1. **Identity:** impersonate the identity with `google.auth.impersonated_credentials`, as D5 does. Internal is
   the internal analyst; tenant A is `sa-tenant-a-user`. Whoever runs it needs token creator on those accounts,
   never on the writer.
2. **Each query run:**
   - `QueryJobConfig(use_query_cache=False, maximum_bytes_billed=2 * 1024**3, query_parameters=...)`;
   - job labels: `bench_run_id`, `bench_setup`, `bench_identity`, `bench_query`, `bench_run_no`. The labels let
     the runner and the cost model find these jobs in `JOBS_BY_PROJECT`. **(added)**
   - record the client-side wall time too.
3. **Run 1 is cold,** the first run after a set-up change. Runs 2–10 are warm. Run the queries in the order
   q01 run 1, q02 run 1, …, then the warm runs, so each query's first run is really its first in that cell.
4. **A failed query is a result, not a crash.** Record `error_reason` (for example, `bytesBilledLimitExceeded`)
   and carry on.
5. **After the cell finishes,** wait about a minute, then read the jobs back as Dev 1 (the runner identity needs
   `bigquery.jobs.listAll`, which the tenant identities don't have):
   ```sql
   SELECT
     job_id, user_email, reservation_id,
     (SELECT value FROM UNNEST(labels) WHERE key = 'bench_query')  AS query_id,
     (SELECT value FROM UNNEST(labels) WHERE key = 'bench_run_no') AS run_no,
     TIMESTAMP_DIFF(end_time, start_time, MILLISECOND)              AS duration_ms,
     total_bytes_processed, total_bytes_billed, total_slot_ms, cache_hit,
     bi_engine_statistics.bi_engine_mode,
     TO_JSON_STRING(bi_engine_statistics.bi_engine_reasons)          AS bi_engine_reasons,
     error_result.reason                                             AS error_reason
   FROM `region-us-central1`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
   WHERE creation_time >= @cell_started_at
     AND EXISTS (SELECT 1 FROM UNNEST(labels) WHERE key = 'bench_run_id' AND value = @run_id)
   ```
6. **Write** one row per run to `ops_dev.benchmark_result`:

   | Column                                              | Notes                                                           |
   | --------------------------------------------------- | --------------------------------------------------------------- |
   | `run_id`, `setup`, `identity`, `dataset`, `git_sha` | One `run_id` per cell                                           |
   | `query_id`, `variant`, `run_no`, `is_cold`          |                                                                 |
   | `job_id`, `started_at`, `duration_ms`, `client_ms`  |                                                                 |
   | `total_bytes_processed`, `total_bytes_billed`, `total_slot_ms` |                                                      |
   | `bi_engine_mode`, `bi_engine_reasons`               | `FULL`, `PARTIAL` or `DISABLED`, and why                        |
   | `reservation_id`                                    | Proves the Enterprise cell ran on the reservation **(added)**   |
   | `cache_hit`, `row_count`, `result_fingerprint`, `error_reason` | `cache_hit` must always be false                     |

   Create the table in Terraform, in the `ops_{env}` module, partitioned on `DATE(started_at)`.
7. **Summary view** `ops_dev.benchmark_summary`: p50 and p95 per query and cell, over the warm runs only, with
   the cold run beside them.
   ```sql
   SELECT setup, identity, dataset, query_id,
     APPROX_QUANTILES(duration_ms, 100)[OFFSET(50)]      AS p50_ms,
     APPROX_QUANTILES(duration_ms, 100)[OFFSET(95)]      AS p95_ms,
     ANY_VALUE(cold.duration_ms)                          AS cold_ms,
     APPROX_QUANTILES(total_bytes_billed, 100)[OFFSET(50)] AS p50_bytes_billed,
     APPROX_QUANTILES(total_slot_ms, 100)[OFFSET(50)]      AS p50_slot_ms,
     COUNTIF(bi_engine_mode = 'FULL')                     AS bi_full_runs,
     COUNTIF(error_reason IS NOT NULL)                    AS errors
   FROM ops_dev.benchmark_result AS r
   LEFT JOIN (SELECT run_id, query_id, duration_ms FROM ops_dev.benchmark_result WHERE is_cold) AS cold
     USING (run_id, query_id)
   WHERE NOT r.is_cold
   GROUP BY setup, identity, dataset, query_id
   ```
   With 9 warm runs, p95 is close to the slowest run. Say so in the report.
8. **`--check-expected`:** on `wh_dev`, compare each result with `expected/<query>.csv`. On `scale`, compare the
   three variants of q9 and of q10 with each other (the AT-34 check that native views equal their dbt tables).
9. **`--dry-run`:** dry-run every variant as each identity and print the bytes each would bill. Used for the
   budget check before Day 11 (section 8).
10. **Tests** in `scripts/benchmark/tests/`: SQL templating, label building, percentile maths on a fixture.

**Done when:** a dry run of 2 queries × 2 runs works end to end on `wh_dev` and lands in
`ops_dev.benchmark_result`. Run the full 14 × 10 on `wh_dev` once on Day 10 as a rehearsal. **(added)**

**Watch out:**

- `JOBS_BY_PROJECT` can lag by a few seconds to minutes. Read the jobs back after the cell finishes, not after each
  query.
- Use the `end_time − start_time` server duration as the latency in the report. Keep the client time to explain any
  gap.

### F4. Reservations in Terraform (Dev 1, Dev 4 reviews, Days 9–10)

**What:** BI Engine and Enterprise reservations that exist only while a flag is on. Both flags default to `false`.

**Steps:**

1. Module `terraform/modules/reservations`, called from `terraform/shared`, region `us-central1` (D-21):

   ```hcl
   variable "enable_bi_engine" {
     type    = bool
     default = false
   }

   variable "enable_enterprise_reservation" {
     type    = bool
     default = false
   }

   resource "google_bigquery_bi_reservation" "bench" {
     count    = var.enable_bi_engine ? 1 : 0
     project  = var.project_id
     location = var.region
     size     = 10 * 1024 * 1024 * 1024      # 10 GB
   }

   resource "google_bigquery_reservation" "bench" {
     count             = var.enable_enterprise_reservation ? 1 : 0
     project           = var.project_id
     location          = var.region
     name              = "poc-bench-enterprise"
     edition           = "ENTERPRISE"
     slot_capacity     = 0                    # no baseline
     ignore_idle_slots = false
     autoscale { max_slots = 100 }
   }

   resource "google_bigquery_reservation_assignment" "bench" {
     count       = var.enable_enterprise_reservation ? 1 : 0
     project     = var.project_id
     location    = var.region
     reservation = google_bigquery_reservation.bench[0].id
     assignee    = "projects/${var.project_id}"
     job_type    = "QUERY"
   }
   ```

   Check the attribute names against the Google provider version pinned in `.terraform.lock.hcl` (8.12.0) before
   merging.
2. Put both flags in `terraform/shared/terraform.tfvars`, set to `false`.
3. Label the reservation `poc=phase2` where the resource supports labels.
4. Check the plans:
   - both off: `terraform plan` shows no reservation;
   - `-var enable_bi_engine=true`: it shows only the BI Engine reservation;
   - `-var enable_enterprise_reservation=true`: it shows the reservation and the assignment.
5. Add "Reservations: create and destroy" to the runbook (E13, Dev 4).

**How a flag is switched on the day (added):** change `terraform.tfvars` in a small pull request. Dev 2 reviews the
`shared` plan, as for every `shared` change. Merge, and CD applies it. Allow 30–45 minutes per switch.

- If CI is too slow on the day, Dev 1 may apply from a laptop with `-var`, but must merge the matching `tfvars`
  change straight away.
- Otherwise the next merge to `main` will undo the reservation in the middle of a run, and E12's "`shared` plan
  shows no changes" check will fail.

**Done when:** `plan` with a flag on shows its reservation; with both off it shows nothing.

### F2. Scale data (Dev 1, Dev 3 helps, Days 10–11)

**What:** `scripts/scale/build_scale.sql` fills the shared `scale` dataset with copies of `wh_dev` across about 3
years and 200 tenants. The micro-batch never reads it.

**Steps:**

1. **Dataset** `scale` in `us-central1`, in Terraform (`terraform/shared`), with label `poc=phase2`.
2. **Count the source rows** and pick the multiplier:
   ```sql
   SELECT COUNT(*) FROM wh_dev.fct_alert_history WHERE event_date >= '2000-01-01';
   -- multiplier = CEIL(50e6 / that count)
   ```
3. **Dry-run** the `fct_alert_history` statement with that multiplier to check the bytes, then run it. The plan's
   sample is in section 11, task F2.
4. **Build every table the queries read,** with the same multiplier and the same key rule, and with the same
   schema, partitioning and clustering as `wh`:

   | Table                    | Kind           | Notes                                                   |
   | ------------------------ | -------------- | ------------------------------------------------------- |
   | `fct_alert_history`      | Fact           | About 50 million rows: the target                       |
   | `fct_alert`              | Fact           | q10 base, and the source for the trend marts            |
   | `fct_case`               | Fact           | q8                                                      |
   | `fct_wheel_event`        | Fact           | q9 base                                                 |
   | `dim_store`, `dim_device`, `dim_account` | Dimensions | q7 and joins                                    |
   | `mv_store_health`        | dbt table      | q1, q5                                                  |
   | `mv_current_issues`, `mv_downtime_interval`, `mv_alert_trend_weekly` | dbt tables | q2, q4, q6                    |
   | `mv_alert_trend_daily`   | Native view **and** table (`mv_alert_trend_daily_tbl`) | q10 `mv` and `tbl`    |
   | `mv_cart_count_daily`    | Native view **and** table (`mv_cart_count_daily_tbl`)  | q9 `mv` and `tbl`     |
   | `map_tenant_access`      | Security       | Test identities mapped to a few of the 200 tenants      |

5. **Key rule (added):** the plan's sample changes `tenant_id` per copy but keeps `store_id`. The same store would
   then belong to many tenants, and the `dim_store` joins in q7 would multiply rows. Suffix the store and device
   ids with the copy number in every fact **and** dimension, and derive the tenant from the suffixed store:
   ```sql
   CONCAT(h.store_id, '-', CAST(m AS STRING))                                  AS store_id,
   CONCAT('T', CAST(MOD(ABS(FARM_FINGERPRINT(CONCAT(h.store_id, '-', CAST(m AS STRING)))), 200) AS STRING)) AS tenant_id,
   ```
6. **Facts:** `require_partition_filter = TRUE`, as in `wh`.
7. **Security:** apply the same two policies as D4, with `wh_{env}` and `sec_{env}` replaced by `scale`. The
   all-rows policy covers the writer and the internal analyst; the tenant policy covers `sa-tenant-a-user` and
   `sa-tenant-b-user`. Map tenant A to 2–3 of the 200 tenants, so a tenant sees about 1% of the rows.
8. **Reader access (added):** the test identities have viewer on `wh_{env}` only. Grant the internal analyst and
   `sa-tenant-a-user` viewer on `scale`, in Terraform, for Days 11–12.
9. **Native views:** create them only after the base table and its policies exist. If spike 4 said "no", create
   them for internal benchmarking only and write down why (C11, step 4).
10. **Checks:**
    ```sql
    SELECT COUNT(*) AS row_count, COUNT(DISTINCT event_date) AS days, COUNT(DISTINCT tenant_id) AS tenants
    FROM scale.fct_alert_history WHERE event_date >= '2000-01-01';
    ```
    - about 50 million rows, about 1,095 days, 200 tenants;
    - rows spread across days, not piled on a few (check the largest partition);
    - both policies on every tenant-scoped `scale` table (`bq ls --row_access_policies` or the API);
    - as tenant A: only tenant A's ids come back;
    - a query on a fact without a date filter fails.

**Done when:** `scale.fct_alert_history` has about 50 million rows and the policies are in place.

**Watch out:**

- Build in BigQuery, not Python. One `CREATE TABLE ... AS` per table.
- `scale` is about 10 GB. Storage is cheap, but delete it on Day 12.

### F5. Looker Studio report (Dev 5, Day 11)

**What:** a report on `wh_dev` that runs each viewer's queries as that viewer, so the row policies apply. It is
the dashboard part of AT-24, checked with Dev 2 in D10.

**Steps:**

1. **Before Day 11 (added):** confirm the two team members' Google accounts are in `store_access` (tenants A and B),
   appear in `sec_dev.map_tenant_access`, are in the tenant policy's grantee list, and have viewer on `wh_dev` and
   job user.
2. **Data sources:** `wh_dev.mv_store_health` and `wh_dev.fct_alert`, as BigQuery tables.
3. **Credentials:** set "Data credentials" to **Viewer** on both data sources.
4. **Partition filter:** on `fct_alert`, tick "use `alert_date` as date range dimension", so every chart sends a
   partition filter. Add a date range control with a sensible default (last 30 days).
5. **Charts:**
   - store health table: store, colour, reason, owner;
   - a count of stores by colour;
   - an alert trend by day from `fct_alert`.
   - Include the `tenant_id` column in one table, so the screenshots show which tenant each row belongs to.
6. **Sharing:** with the two tenant users and the internal analyst.
7. **Check (D10):** each of the three opens the report.
   - Tenant A sees only tenant A's rows; tenant B only tenant B's.
   - The internal analyst sees all.
   - Take screenshots of each for the security report.
8. **During the BI Engine afternoon:** open the report as each user and note the BI Engine mode of the jobs
   Looker Studio sends (Looker Studio adds its own job labels; find the jobs by `user_email` and time).

**Done when:** two tenant users see different rows in the same report.

**Watch out:** without the partition filter tick, charts on `fct_alert` fail, because `wh` requires a filter.

### F6. Benchmark runs (Dev 1, Dev 5, Dev 2, Days 11–12)

**What:** fill every cell of the matrix. Section 5 is the minute-by-minute run sheet.

**The matrix:**

| Set-up                   | When               | Identities                                     | Dataset |
| ------------------------ | ------------------ | ---------------------------------------------- | ------- |
| On-demand                | Day 11 morning     | Internal, tenant A                             | `scale` |
| On-demand with BI Engine | Day 11 afternoon   | Internal, tenant A; Looker Studio users (on `wh_dev`) | `scale` |
| Enterprise               | Day 12 morning     | Internal, tenant A                             | `scale` |

- 14 variants × 10 runs × 2 identities × 3 set-ups = **840 query runs**. q7 runs as internal only, so a little
  fewer.
- **Security on or off is measured by identity:** the internal identity passes through the all-rows policy;
  tenant A passes through the tenant policy.
- Dev 1 runs the internal cells; Dev 2 runs the tenant A cells (Dev 2 has the impersonation set up from D5).
  Dev 5 checks each cell's summary as it lands.
- **While the Enterprise reservation is assigned,** every query in the project uses it, the micro-batch included.
  That's fine for half a day.

**Done when:** every cell of the matrix has results, and the reservations are destroyed by Day 12 noon.

### F7. Cost model (Dev 1, Day 12)

**What:** `docs/poc2/cost-model.md`. The monthly cost of each pricing option for three scenarios, and the
break-even point. Start the draft on Day 11 with the on-demand figures; fill in the Enterprise figures on Day 12.
**(added)**

**Steps:**

1. **Measured workload,** from `region-us-central1.INFORMATION_SCHEMA.JOBS_BY_PROJECT`:
   - **one normal day of micro-batch runs (Day 9):** jobs by `sa-dwh-writer-dev` on that day. Sum
     `total_bytes_billed` and `total_slot_ms`;
   - **the benchmark queries:** from `ops_dev.benchmark_result`, the p50 bytes and slot time per query;
   - **storage:** `INFORMATION_SCHEMA.TABLE_STORAGE` for `wh_dev`, `build_dev`, `raw_*` and `scale`, active and
     long-term logical bytes.
2. **Three scenarios per month:**

   | Scenario | Workload                                                                         |
   | -------- | -------------------------------------------------------------------------------- |
   | S1       | The POC workload running all the time, plus 20 dashboard users × 50 queries a day |
   | S2       | S1 with 10 times the data                                                        |
   | S3       | S1 with 100 times the data                                                       |

   - **Dashboard queries:** cost each one as the mean of q1–q6's p50 bytes and slot time as a tenant. State the
     number of days a month assumed (30, or about 22 working days).
   - **10× and 100× (added):** we have each query at two sizes, `wh_dev` and `scale`. Use the observed growth in
     bytes and slot time between them to scale up, rather than assuming linear growth. Write down the method,
     and show the linear figure beside it.
3. **Prices** from the BigQuery pricing page on the day, with the date written down. **Never in code.**
   - on-demand per TiB;
   - Enterprise per slot-hour;
   - BI Engine per GiB-hour;
   - storage, active and long-term.
4. **On-demand cost** = TiB billed × price, after the free monthly allowance.
5. **Editions cost** = slot-hours × price.
   - Slot-hours = `SUM(total_slot_ms) / 3.6e6`, plus an allowance for autoscaling steps and the one-minute
     minimum, plus any baseline × 730 hours.
   - **Measure the allowance (added):** from the Day 12 Enterprise run, compare the slots the autoscaler actually
     held (per minute, from `INFORMATION_SCHEMA.RESERVATIONS_TIMELINE`) with `SUM(total_slot_ms)` for the same
     window. Their ratio is the overhead factor. If the Enterprise run was cut, use an assumed factor and say so.
6. **BI Engine:** 10 GB × hours a month × price, as an extra line on either option.
7. **Break-even:** the monthly TiB at which on-demand and editions cost the same. Show it for each scenario.
   - If editions cost per TiB (slot-hours per TiB × slot price) is above the on-demand price at every volume, there
     is no break-even with autoscaling only. Say so, and show where a baseline or a commitment would change that.
8. **The document says** that it is based on a generated workload: it shows the method, not GKS's cost. It lists
   every assumption.

**Outline of `cost-model.md`:**

1. Statement: generated workload; method, not GKS's bill.
2. Prices used, with the date read.
3. Measured workload: micro-batch day, benchmark queries, storage.
4. Scenarios S1–S3: assumptions.
5. Monthly cost table: scenario × (on-demand, Enterprise, + BI Engine, storage).
6. Break-even per scenario, with a chart of cost against TiB a month.
7. Every assumption, numbered.
8. What would change the answer at GKS (real `g2_bi_core` workload, real users, commitments).

**Done when:** AT-30 passes (cost part).

### F8. Benchmark report (Dev 1, Dev 5, Day 12)

**What:** `docs/poc2/benchmark-results.md`.

**Outline:**

1. **Statement:** generated workload; figures show how to decide, not GKS's performance.
2. **Set-up:** row counts and sizes of `scale`; the identities; the 2 GB cap; cache off; 10 runs per cell, run 1
   cold; the date and commit.
3. **Results per query:** one table per set-up. Rows are query variants; columns are p50 and p95 latency, cold
   latency, bytes billed, slot ms, BI Engine mode. Internal and tenant A side by side.
4. **Native views compared:** q9 and q10, `mv` against `tbl` against `base`: latency, bytes, slot time, and proof
   that the three give the same answer (AT-34). If spike 4 limited the views to internal users, say so here.
5. **Security overhead:** tenant A against internal, per query. Explain what the tenant policy's subquery costs.
6. **Partition pruning and clustering (AT-34):**
   - bytes billed for a dated query against the full table size;
   - the failed query without a date filter, with its error;
   - for one query, the query plan stages from the console.
7. **BI Engine:** which queries were accelerated (`FULL`, `PARTIAL`, `DISABLED`) and the reasons given. Include the
   Looker Studio jobs.
8. **Enterprise:** latency against on-demand; `reservation_id` on every run, proving the reservation was used.
9. **Findings:** 5–8 plain-English points, each tied to a table above.
10. **Limits:** generated data, small warm-run count, a shared project with the micro-batch running.

Dev 1 writes sections 2–8; Dev 5 writes 1, 9 and 10, and edits the whole.

**Done when:** AT-30 passes (benchmark part).

### F9. _Stretch:_ Power BI DirectQuery (Dev 5)

Only if G8 is on track on Day 11. Connect Power BI Desktop to `wh_dev` in DirectQuery mode as a tenant user, build
one page on `mv_store_health`, and check it shows only that tenant's rows. First to cut (section 11).

---

## 5. Benchmark days run sheet (Days 11–12)

Times are the team's time zone. Each switch of a flag is a merged pull request (F4). Before each cell, check the
set-up really changed.

**Day 10, end of day (pre-flight) (added):**

- [ ] `scale` built and checked (F2, step 10).
- [ ] `run.py --dry-run --dataset scale` for both identities. Total bytes × 10 runs × 2 set-ups on demand is well
      inside the remaining free allowance (section 8).
- [ ] The full rehearsal on `wh_dev` has run cleanly.
- [ ] The `enable_bi_engine=true` pull request is open, with the plan reviewed.

**Day 11**

| Time   | Who          | Step                                                                                                       |
| ------ | ------------ | ---------------------------------------------------------------------------------------------------------- |
| 09:00  | Dev 1        | Check `scale` once more. Confirm no reservation exists                                                     |
| 09:30  | Dev 1, Dev 2 | **Cell 1: on-demand.** `run.py --setup ondemand --identity internal`, then `--identity tenant_a`           |
| 11:30  | Dev 5        | Check the cell 1 summary: 10 runs per query, no `cache_hit`, errors explained                              |
| 12:00  | Dev 1        | Merge `enable_bi_engine=true`. Wait for CD. Check BI Engine capacity in the console                        |
| 13:00  | Dev 1, Dev 2 | **Cell 2: BI Engine.** Both identities                                                                      |
| 14:30  | Dev 5, Dev 2 | Looker Studio check (F5, D10) as the two tenant users and the internal analyst. Screenshots                |
| 16:00  | Dev 5        | Check the cell 2 summary: at least some queries show `bi_engine_mode` other than `DISABLED`, or reasons recorded |
| 17:00  | Dev 1        | Merge `enable_bi_engine=false`. **BI Engine destroyed.** Check in the console that capacity is gone         |
| 17:30  | Dev 1        | Open the `enable_enterprise_reservation=true` pull request, plan reviewed                                  |

**Day 12**

| Time   | Who          | Step                                                                                                       |
| ------ | ------------ | ---------------------------------------------------------------------------------------------------------- |
| 08:30  | Dev 1        | Merge `enable_enterprise_reservation=true`. Wait for CD. Run one test query; check its `reservation_id`     |
| 09:00  | Dev 1, Dev 2 | **Cell 3: Enterprise.** Both identities                                                                     |
| 11:00  | Dev 1        | Record the `RESERVATIONS_TIMELINE` window for the F7 overhead factor                                       |
| 11:30  | Dev 1        | Merge `enable_enterprise_reservation=false`. **Reservation destroyed**                                     |
| 12:00  | Dev 1        | **Check both in the console:** no reservation, no assignment, BI Engine capacity 0. Note it for G8          |
| 12:00– | Dev 1, Dev 5 | F7, F8                                                                                                     |
| Teardown | Dev 1      | Delete `scale` (section 8)                                                                                  |

If a cell overruns, cut the warm runs from 10 to 5 for that cell before cutting a cell. Write down that you did.

---

## 6. Acceptance tests

| Test  | What it proves         | How to run it                                     | Passes when                                                                                                                         | Owner        | Gate |
| ----- | ---------------------- | ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------ | ---- |
| AT-24 | Tenant isolation everywhere (dashboard part) | D10 with F5                   | Each tenant sees all its own rows and none of another's through Looker Studio                                                        | Dev 2, Dev 5 | G8   |
| AT-30 | Benchmark and cost model | F6–F8                                           | p50 and p95 latency, bytes and slot time per query and set-up; native views compared; cost model with assumptions and break-even; says "generated workload" | Dev 1 | G8 |
| AT-34 | Physical design        | C11 and the benchmark                             | Every `wh` fact partitioned, filter required, clustered with `tenant_id` first; a query without a date filter fails; dated queries bill only their partitions; the two native views return the same results as their dbt tables | Dev 1 | G8 |

Put the automated parts as scripts so `scripts/acceptance/run_all.py` can re-run them before G8:

- `scripts/acceptance/at30_benchmark.py`: every cell in `ops_dev.benchmark_result` has 10 runs per query, both
  documents exist and contain "generated workload".
- `scripts/acceptance/at34_physical_design.py`:
  - table options of every `wh_dev` fact;
  - a query without a date filter fails;
  - bytes billed for a one-day query is well under the table size;
  - `mv` equals `tbl` for q9 and q10 on `wh_dev`.

AT-34 runs on `wh_dev` so it can still run after `scale` is deleted. The scale evidence goes in
`benchmark-results.md`.

---

## 7. Gate checklist

Items marked **(plan)** are the plan's gate criteria that involve POC F or its dependencies. Items marked
**(extra)** are added here as POC F readiness checks. They don't block the gate in the plan; the team decides
whether to enforce them.

**G5, Day 2**

- [ ] **(plan)** Spikes answered (0.9), including spike 4 (Dev 1)
- [ ] **(plan)** Budget alerts live (0.8)
- [ ] **(plan)** D-21 confirmed: reservations in `us-central1`

**G6, Day 6**

- [ ] **(extra)** The six POC 1 reader questions listed (F1, step 1)

**G7, Day 10**

- [ ] **(extra)** F1: 14 variants reviewed, expected answers saved
- [ ] **(extra)** F3: the dry run works; the rehearsal on `wh_dev` is done
- [ ] **(extra)** F4: plans correct with each flag on and both off
- [ ] **(extra)** F2: `scale` built and checked, so Day 11 can start on time
- [ ] **(extra)** Looker Studio accounts mapped to tenants A and B (F5, step 1)

**G8, Day 12**

- [ ] **(plan)** AT-24 (Looker Studio), AT-30 and AT-34 pass
- [ ] **(plan)** Every earlier test still passes (`run_all.py`)
- [ ] **(plan)** Reservations destroyed, checked in the console
- [ ] **(plan)** Teardown done per the runbook, including deleting `scale`
- [ ] **(plan)** Knowledge-sharing demo of POC F: the method, the matrix, and the cost trade-offs

---

## 8. Budget and teardown

**POC F's share of the budget (plan, section 16):**

| Item                               | Control                                                 | Rough cost      |
| ---------------------------------- | ------------------------------------------------------- | --------------- |
| BI Engine, 10 GB                   | Day 11 afternoon only; destroyed the same evening        | About 3 USD     |
| Enterprise (autoscaling, no baseline) | Day 12 morning only                                   | About 2–5 USD   |
| Benchmark queries                  | `maximum_bytes_billed` 2 GB per query; date filters; cache off but scale only 10 GB | Inside the free allowance, or a few USD |
| `scale` storage, about 10 GB       | Deleted on Day 12                                       | Under 1 USD     |

**Query bytes check before Day 11 (added):** about 560 on-demand runs (two on-demand cells), capped at 2 GB each,
could in theory bill about 1.1 TB. Real dated queries should bill MBs each.

- On Day 10, `run.py --dry-run` gives the real estimate.
- If the estimate × runs is more than about 100 GB, stop and look at the queries before Day 11.
- Dev 4 checks the billing report (label `poc=phase2`) every morning, as for the rest of the POC.

**If the 60 USD alert fires:** the team agrees what to stop. For POC F, the plan's fallback is to cut the
Enterprise run and estimate its cost from on-demand slot time (section 11).

**Teardown, Day 12:**

1. Check in the console that both reservations are gone: no reservation, no assignment, BI Engine capacity 0.
   Also check with `SELECT * FROM region-us-central1.INFORMATION_SCHEMA.RESERVATIONS` and `.ASSIGNMENTS`.
2. Both flags are `false` in `terraform/shared/terraform.tfvars` on `main`.
3. Export the `scale` evidence the report needs, then delete `scale`: `bq rm -r -f -d data-lake-poc-512405:scale`.
   Remove the dataset from Terraform in the same pull request, or the next apply recreates it.
4. Remove the Looker Studio users' tenant mappings (plan, risk table), once D10's screenshots are saved.
5. Keep `ops_dev.benchmark_result`: it's small, and it's the evidence.

---

## 9. Risks and fallbacks

| Risk                                                                                       | Effect                                    | What we do                                                                                     | Owner |
| ------------------------------------------------------------------------------------------ | ----------------------------------------- | ---------------------------------------------------------------------------------------------- | ----- |
| Spike 4: a native view isn't allowed on a table with row policies or a required filter     | AT-34 only partly met                     | Create the views for internal benchmarking only; keep the dbt tables in `wh`; write down why    | Dev 1 |
| F2 not ready by Day 11 morning                                                             | Cell 1 slips; the BI Engine window shrinks | Finish F2 on Day 10 with Dev 3; if late, run cell 1 after cell 2 on the same day (both are on-demand) | Dev 1 |
| Dev 1 overloaded (C-series until Day 9, then F)                                            | F slips at G7                             | Dev 3 takes F2's data checks; Dev 5 takes the F3 summary view and the report draft; rebalance at G6 | Dev 5 |
| A flag switch through CD is slow or fails                                                  | A cell starts late; a reservation lives longer | Open each pull request the evening before; laptop apply as a fallback, with `tfvars` merged straight after | Dev 1 |
| A reservation is left running                                              | Cost rises by the hour                    | Destroy times in the run sheet; console check at Day 11 evening and Day 12 noon; G8 item       | Dev 1 |
| BI Engine doesn't accelerate some queries (for example, because of row policies)           | Cell 2 shows little change                | That's a finding, not a failure. Record `bi_engine_reasons` for every run                      | Dev 1 |
| The micro-batch runs during the benchmark and adds noise                                   | Latency spread widens                     | Note micro-batch times in the report; p50 over warm runs absorbs most of it                    | Dev 1 |
| `JOBS_BY_PROJECT` read too early                                                           | Missing rows                              | Read back after each cell; the runner checks it has 10 rows per query                          | Dev 1 |
| Looker Studio needs real Google accounts for tenant users                                  | Part of AT-24 can't run                   | Two team members mapped to tenants for Day 11, then removed                                    | Dev 5 |
| Scaled dimensions don't match scaled facts                                                 | q7 or joins give wrong or multiplied rows | The key rule in F2, step 5                                                                     | Dev 1 |
| dbt `mv_cart_count_daily` uses an exact distinct count                                     | `mv` and `tbl` differ on `active_wheels`  | Same approximate function in both, or a stated tolerance (F1)                                  | Dev 1 |

---

## 10. Open decisions and gaps found while planning

**Decisions from the plan** (confirmed by Dev 5 with the PO at G5):

| Decision | Choice in the plan                                                                   | Affects        |
| -------- | ------------------------------------------------------------------------------------ | -------------- |
| D-21     | Reservations, `scale` and every dataset in `us-central1`                             | F2, F4, F6     |
| D-28     | The publish step owns everything in `wh_{env}`, including the native views           | C11, F2        |

**Gaps found while planning this file (added).** Each needs a yes or no from the team, ideally at G6:

| #   | Gap                                                                                                 | Suggested answer                                                                 |
| --- | --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 1   | F2 is planned for Days 10–11, but cell 1 reads `scale` on Day 11 morning                             | Finish F2 on Day 10, with Dev 3                                                  |
| 2   | Test identities have viewer on `wh_{env}` only, so they can't read `scale`                           | Grant viewer on `scale` to the internal analyst and `sa-tenant-a-user`, in Terraform |
| 3   | How a reservation flag is switched: CD from `tfvars`, or a laptop apply                              | Through a pull request and CD; laptop only as a fallback (F4)                    |
| 4   | The F2 sample keeps `store_id` while changing `tenant_id`, which breaks dimension joins at scale     | Suffix store and device ids with the copy number (F2, step 5)                    |
| 5   | `APPROX_COUNT_DISTINCT` in the native view against the dbt table's count                             | Same function in both (F1)                                                       |
| 6   | Table names can't be BigQuery query parameters                                                       | `{dataset}` placeholders filled in by the runner (F1)                            |

---

## 11. If time runs short

From the plan's cut order, the items that touch POC F, first cut first:

1. **F9,** Power BI (stretch).
2. **The second native view, `mv_alert_trend_daily`.** Keep its dbt table in `wh`; q10 then compares `tbl` with
   `base` only.
3. **The Enterprise reservation run.** Estimate the editions cost from the slot time measured on demand, with an
   assumed overhead factor, and say so in the cost model.

Before cutting a cell, cut warm runs from 10 to 5 for that cell, and write it down.

**Never cut:** the budget controls, which here means the reservations being destroyed on time and `scale` being
deleted.
