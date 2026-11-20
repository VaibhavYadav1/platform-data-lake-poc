# POC C: dbt validations (required checks, implementation and flow)

|                  |                                                                                                                                  |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **Status**       | Draft for review. Nothing here is built yet: the `dbt/` folder in `platform-data-lake-poc` holds only READMEs                     |
| **Owner**        | Shreyash (POC C validations)                                                                                                     |
| **Covers**       | Tasks C1 (conventions), C7 (validation rules), C9 (DQ41), C12 (freshness); checks DQ33–DQ43; the POC 1 rules that still apply      |
| **Sources**      | [GKS-POC-Phase2-detailed-plan.md](GKS-POC-Phase2-detailed-plan.md) sections 0.4, 4.3, 8, 12, 13 and Appendix A; [GKS-POC-Phase2-POC-C-dbt.md](GKS-POC-Phase2-POC-C-dbt.md); POC 1 [validation-rules.md](../../data-lake-ETL-tool/docs/validation-rules.md), [engine.py](../../data-lake-ETL-tool/app/validation/engine.py) and `app/validation/rules/` |
| **Last updated** | 2026-11-20                                                                                                                       |

Anything marked **Proposed** is my suggestion and needs agreement from the POC C owner. Anything marked **Plan** is
already decided in the plan.

---

## 1. Purpose

POC 1 validated rows in Python before writing them ([engine.py](../../data-lake-ETL-tool/app/validation/engine.py)):
a bad row was rejected with all its reasons and written to `poc_ops.rejected_records`. POC 2 builds the warehouse in
dbt, inside BigQuery. This document says:

1. how validation works in dbt at the code level (section 2);
2. where in the pipeline each check sits (section 3);
3. which checks this POC needs, and why (section 4);
4. how each one is written in dbt (section 5);
5. the full flow from writing a rule to reviewing results (section 6).

---

## 2. How dbt validation works at the code level

### 2.1 Two different tools: rules in models, and tests

The most important point: **a dbt test never changes data.** It only reports, or stops the build. So there are two
ways to validate, and each check must use the right one.

| Tool                      | What it does                                                                       | When to use it                                         | Example          |
| ------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------ | ---------------- |
| **Rule inside a model**   | SQL in the model tags each row with `_dq_status` and `_dq_reasons`. Later models filter on the tag | The bad row must be **kept out** of the published tables (quarantine) or given a safe value | DQ33, DQ34, DQ38, DQ36, DQ37 |
| **Test**                  | A `SELECT` that returns the **failing rows** after the model is built              | The result must be **checked**: report it (warn) or stop publishing (error) | `unique`, DQ41, DQ43 |

### 2.2 What a test is

Every dbt test compiles to a `SELECT` that returns the rows that break the rule. **0 rows means pass.**

This line in a model's `.yml`:

```yaml
- name: incident_id
  data_tests: [unique]
```

compiles to (simplified):

```sql
select incident_id as unique_field, count(*) as n_records
from `data-lake-poc-512405`.`build_dev`.`fct_alert`
where incident_id is not null
group by incident_id
having count(*) > 1
```

dbt runs that query, counts the rows and compares the count with the test's thresholds.

### 2.3 Kinds of check dbt offers

| Kind                    | Written in                              | Used for                                                                                 |
| ----------------------- | --------------------------------------- | ---------------------------------------------------------------------------------------- |
| **Built-in generic tests** | The model's `.yml`                   | `unique`, `not_null`, `accepted_values`, `relationships`                                  |
| **Package generic tests** | The model's `.yml`                    | `dbt_utils` (`unique_combination_of_columns`, `expression_is_true`, `recency`), `dbt_expectations` (`expect_column_values_to_match_regex`, `expect_column_values_to_be_between`). Both packages are in the plan (0.4) |
| **Custom generic tests** | `tests/generic/<name>.sql`, used in `.yml` | A rule we reuse on many columns. **Proposed:** `dq_quarantine_count`                  |
| **Singular tests**       | `tests/dqNN_<name>.sql`                | A one-off rule over one or more tables. Plan naming: `dq41_no_personal_data_columns.sql` |
| **Source freshness**     | `sources_<system>.yml`                  | Is the raw data recent enough? Run by `dbt source freshness`                             |
| **Model contracts**      | `contract: {enforced: true}` plus `data_type` per column | Column names and types can't change by accident. On for `build` models (plan 0.4)      |
| **Unit tests**           | `unit_tests:` in a `.yml` (dbt 1.8+)    | Fixed input rows, expected output rows. Tests the model's logic, not the data. Used in AT-18 |

### 2.4 Settings that change how a test behaves

| Setting             | Values                         | Effect                                                                                       |
| ------------------- | ------------------------------ | -------------------------------------------------------------------------------------------- |
| `severity`          | `error` (default), `warn`      | `error`: the test fails and every model downstream is skipped. `warn`: reported, the run goes on |
| `error_if`, `warn_if` | for example `">0"`, `">100"` | Thresholds on the number of failing rows                                                      |
| `where`             | a SQL condition                | Test only some rows, for example the last 3 days of a big fact                               |
| `store_failures`    | `true`                         | Saves the failing rows to a table in `dq_{env}`. **Plan:** on for every test                 |
| `limit`             | a number                       | Caps the stored failing rows                                                                 |
| `tags`              | for example `dq`, `dq41`, `critical` | Lets you run a group: `dbt test --select tag:dq41`                                     |

### 2.5 What happens when dbt runs

```
dbt build
  └─ for each node, in dependency order (from ref() and source()):
       1. run the model         CREATE OR REPLACE TABLE ... AS SELECT ...
       2. run its tests         each test = SELECT returning failing rows
              0 rows                   → PASS
              rows, severity warn      → WARN   (run continues)
              rows, severity error     → FAIL   (models downstream are SKIPPED)
  └─ write target/run_results.json  (status, failure count, time for every node)
  └─ exit code 0 only if nothing failed
```

- **Micro-batch (plan):** `entrypoint.sh microbatch` runs `dbt build --exclude tag:daily`, then `publish.py` **only
  if dbt exited 0**. So a failing `error` test means nothing is published, and readers keep the last good version.
- **Quarantine is not a test failure.** A quarantined row is filtered by SQL, so the build still passes. That's why
  section 5.6 adds a warn test that reports the quarantine count.

---

## 3. Where validation sits in the pipeline

```
SOURCE        raw_g2, raw_crm, raw_lpos, sim_g2_datalake
   │  ① source freshness, source key tests                     (C12, DQ40)
   ▼
STAGING       stg_{env}: stg_g2__*, stg_crm__*, stg_lpos__*  (views)
   │  ② current row per key, dedup, casting, key tests         (DQ35, POC 1 DUPLICATE_KEY)
   ▼
INTERMEDIATE  prep_{env}: int_alert__validated, int_store__tenant, int_account__tenant
   │  ③ ROW RULES → _dq_status, _dq_reasons                    (DQ33, DQ34, DQ38, DQ37, POC 1 row rules)
   │        └─ QUARANTINE ──► dq_{env}.quarantine_alert
   ▼
BUILD         build_{env}: dim_*, fct_*  (contracts enforced)
   │  ④ key tests, relationships, accepted values, contracts    (C1, DQ36, DQ43, POC 1 lookups)
   ▼
ROLLUPS       build_{env}: mv_*
   │  ⑤ business-result tests                                   (golden scenarios C6)
   ▼
WHOLE BUILD   ⑥ personal-data test over build_{env}             (DQ41)
CI            ⑦ convention check on every pull request          (C1, AT-36)
OUTSIDE dbt   DQ39 (daily full load), DQ42 (CRM loader)
```

### POC 1 compared with POC 2

| POC 1 (Python)                                                   | POC 2 (dbt)                                   |
| ---------------------------------------------------------------- | --------------------------------------------- |
| `poc_stage_<env>`: every column as text                          | `raw_g2`: real types from PostgreSQL          |
| Warehouse load step 2: resolve duplicates                        | ② staging (`cdc_current_state`)               |
| Step 4, layer 1: generic checks read from the model (`constraints_of`) | ④ generic tests in each model's `.yml`  |
| Step 4, layer 2: table rules in `app/validation/rules/<table>.py` | ③ row rules in `int_*__validated` and ④/⑤ singular tests |
| Step 6: rejected rows to `poc_ops.rejected_records`              | `dq_{env}.quarantine_alert` and the `store_failures` tables |
| Rejected rows never reach `poc_dwh`                              | Critical rows never reach `build`; an `error` test stops the publish |

---

## 4. Required validations

### 4.1 Structural checks on every `build` model (C1: Plan)

Every model in `build_{env}`:

- `unique` and `not_null` on its key;
- a description on every column;
- an enforced contract (a `data_type` on every column).

A CI check fails the pull request if any of these is missing (section 5.9).

| Model               | Key                                    | Model               | Key                          |
| ------------------- | -------------------------------------- | ------------------- | ---------------------------- |
| `dim_store`         | `store_id`                             | `fct_case`          | `case_id`                    |
| `dim_device`        | `device_id`                            | `dim_offender`      | (`tenant_id`, `offender_token`) |
| `dim_alert_type`    | `alert_type_id`                        | `dim_wheel`         | `wheel_id`                   |
| `dim_date`          | `date_day`                             | `fct_wheel_event`   | `event_id`                   |
| `dim_account`       | `account_id`                           | `fct_work_order`    | `work_order_id`              |
| `fct_alert`         | `incident_id`                          | `map_tenant_access` | (`principal`, `tenant_id`)   |
| `fct_alert_history` | `history_id`                           | `mv_*` rollups      | their grain, for example (`tenant_id`, `store_id`, `alert_date`) |

Composite keys use `dbt_utils.unique_combination_of_columns`.

### 4.2 New checks DQ33–DQ43 (Plan, section 13)

| DQ   | Rule                                              | Layer | dbt mechanism                                       | Severity and action                   | Proposed file                                   |
| ---- | ------------------------------------------------- | ----- | --------------------------------------------------- | ------------------------------------- | ----------------------------------------------- |
| DQ33 | Alert names an unknown device or store            | ③     | Row rule in `int_alert__validated`                  | Critical: quarantine                  | `models/intermediate/alert/int_alert__validated.sql` |
| DQ34 | Event time more than 5 minutes in the future      | ③     | Row rule (`var('future_tolerance_minutes')`)        | Critical: quarantine                  | same                                            |
| DQ35 | Duplicate case `event_id`                         | ②     | `qualify row_number()` in staging, plus a warn test that counts the duplicates | Warning: deduplicated, count reported | `stg_lpos__case_event.sql`, `tests/dq35_duplicate_case_events.sql` |
| DQ36 | CRM account with an unknown type code             | ④     | `coalesce` to `UNKNOWN` in the model, plus a warn test | Warning: `UNKNOWN`, not a customer  | `dim_account.sql`, `dim_account.yml`            |
| DQ37 | Store with no active CRM store record (no tenant) | ③     | Null `tenant_id` in the model, plus a warn test     | Warning: internal-only                | `int_store__tenant.sql`, `tests/dq37_store_without_tenant.sql` |
| DQ38 | Alert resolved before it opened                   | ③     | Row rule                                            | Critical: quarantine                  | `int_alert__validated.sql`                      |
| DQ39 | Incremental facts differ from the full rebuild    | —     | Daily full-load script (POC E, E6), not a dbt test  | Error, to be explained                | —                                               |
| DQ40 | No new CRM export in 75 minutes                   | ①     | `freshness` in `sources_crm.yml`; `freshness_check` (E7) alerts | Freshness error                | `models/sources/sources_crm.yml`                |
| DQ41 | Personal data in `build`                          | ⑥     | Singular test on `INFORMATION_SCHEMA.COLUMNS`; daily value scan | Error: fails the build     | `tests/dq41_no_personal_data_columns.sql`       |
| DQ42 | More than half the CRM accounts change at once    | —     | CRM loader (POC B, B5), not dbt                     | Error: export held                    | —                                               |
| DQ43 | Wheel event names an unknown wheel                | ④     | `relationships` test with `severity: warn`          | Warning: kept, flagged                | `fct_wheel_event.yml`                           |

### 4.3 POC 1 rules: what carries over (C7)

**What I checked:**
- the rules in [validation-rules.md](../../data-lake-ETL-tool/docs/validation-rules.md);
- the POC 1 stage columns in `app/models/stage/tables/`;
- the POC 2 changes in Appendix A of the plan.

**The five decisions:**

| Decision                  | Meaning                                                                                              |
| ------------------------- | ---------------------------------------------------------------------------------------------------- |
| **Port: quarantine**      | Row rule in `int_*__validated`. The row is kept out                                                  |
| **Port: test**            | A dbt test, `error` or `warn` as stated                                                              |
| **By construction**       | dbt derives the column with a join or a macro, so it can't disagree. Parity (C4, C6) proves it instead of a row check |
| **Enforced at source**    | PostgreSQL types already guarantee it. Listed, not dropped (plan, C7). **Check issue 3 first**        |
| **Not applicable**        | The POC 1 table is gone in POC 2 (Appendix A)                                                         |

#### POC 1 reasons, mapped to dbt

| POC 1 reason          | dbt equivalent                                                                                      |
| --------------------- | --------------------------------------------------------------------------------------------------- |
| `MISSING_REQUIRED`    | `not_null`                                                                                          |
| `DUPLICATE_KEY`       | Current row per key in staging, plus `unique`                                                        |
| `DUPLICATE_VALUE`     | `unique` on the non-key column                                                                      |
| `BAD_ENUM`            | `accepted_values`, or `relationships` to a seed (`status`)                                          |
| `UNKNOWN_REFERENCE`   | Row rule (quarantine) when the row must be kept out; otherwise `relationships`                       |
| `INCONSISTENT_VALUE`  | Row rule, or a `dbt_utils.expression_is_true` or singular test                                      |
| `BAD_TYPE`            | Enforced at source (typed columns), plus the model contract                                         |
| `BAD_PATTERN`         | Enforced at source **only if** the G2 schema has `CHECK` constraints (issue 3); otherwise `expect_column_values_to_match_regex` |

#### Per-table result

| POC 1 table → POC 2       | POC 1 rule                                                                            | Decision                                                | Severity (**Proposed**) |
| ------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------- | ----------------------- |
| **`dim_brand` → folded into `dim_store`** | name required, unique, no extra spaces                                   | Port: test on `stg_g2__brands`                           | warn                    |
|                           | `ultimate_parent` required, not a brand name                                          | Port: test on `stg_g2__brands`. Tenancy now comes from the CRM (D-23), so this no longer decides access | warn |
| **`dim_team` → `assignee_team_name`** | name required, unique                                                     | Port: test on `stg_g2__teams`                            | warn                    |
| **`dim_user` → `assignee_token`** | email format, email unique                                                    | Not applicable: email never reaches `build` (DQ41)       | —                       |
|                           | active user has a team (DQ03)                                                         | Port: test on `stg_g2__users`                            | warn                    |
| **`dim_alert_type`**      | names required and unique                                                             | Port: `not_null`, `unique`                               | error                   |
|                           | `category_name`, `severity`, `device_type`, `system_type`, `default_priority` in their lists | Port: `accepted_values`                          | error                   |
|                           | booleans                                                                              | Enforced at source                                       | —                       |
|                           | `not_started_next_step_action` required                                               | Port: `not_null`                                         | warn                    |
| **`dim_store`**           | name required; id unique                                                              | Port: `not_null`, `unique`                               | error                   |
|                           | brand exists                                                                          | Port: `relationships` from `stg_g2__stores.brand_id` to `stg_g2__brands` | error  |
|                           | brand and `ultimate_parent` equal the brand's                                         | By construction (join)                                   | —                       |
|                           | country is ISO alpha-2, upper case                                                    | Port: regex `^[A-Z]{2}$`                                  | warn                    |
|                           | region, department, district, state, city required; no gaps in `level_1..7`; `hierarchy_complete` | Port: `not_null` (warn); `hierarchy_complete` by construction | warn       |
| **`dim_device`**          | store required and exists                                                             | Port: `relationships` to `dim_store`                     | error                   |
|                           | `type` one of five device types                                                       | Port: `accepted_values`                                  | error                   |
|                           | `location_class` from the main-door flag                                              | By construction                                          | —                       |
| **`dim_status` → seed `status`** | seven names, unique; `is_closed` only for Resolved; `next_step_action` except Not Started | Port: tests on the seed                          | error                   |
| **`fct_alert_incident` → `fct_alert`** | required columns                                                 | Port: `not_null`                                         | error                   |
|                           | store and device exist                                                                | **DQ33** (quarantine)                                    | critical                |
|                           | alert type exists                                                                     | Port: add `DQ33_UNKNOWN_ALERT_TYPE` to the row rule      | critical                |
|                           | status one of the seven (`BAD_ENUM`)                                                  | Port: `relationships` to seed `status`                   | error                   |
|                           | `priority` P1–P5                                                                      | Port: `accepted_values`                                  | error                   |
|                           | `alert_id` = `ALR-<device>-<alert type>`                                              | Port: `expression_is_true`                               | warn                    |
|                           | device installed at the store (DQ08)                                                  | Port: warn test. **Not** quarantine: the simulator moves devices between stores (plan 4.3) | warn |
|                           | device type equals the alert type's device type                                       | Port: warn test                                          | warn                    |
|                           | brand, hierarchy and alert name copied from parents (DQ09)                            | By construction                                          | —                       |
|                           | `alert_date` = date of the alert time                                                 | By construction                                          | —                       |
|                           | resolved before opened (DQ11)                                                         | **DQ38** (quarantine)                                    | critical                |
|                           | time in the future (DQ12)                                                             | **DQ34** (quarantine), now with a 5-minute tolerance     | critical                |
|                           | open incident at an inactive store (DQ25)                                             | Port: warn test (issue 6)                                | warn                    |
|                           | `is_valid`, `invalid_reason`, `is_open` consistent                                    | By construction: `is_open_alert()` macro (C8)            | —                       |
|                           | resolved exactly when the status is closed (DQ13)                                     | Port: singular test                                      | warn                    |
|                           | no overlapping incidents per `alert_id` (DQ29)                                        | Port: singular test                                      | warn                    |
| **`fct_alert_history`**   | required columns; `history_id` format `H` + 7 digits                                  | `not_null`; format per issue 3                           | error / warn            |
|                           | incident exists                                                                       | Port: `relationships` to `fct_alert` (see issue 5)       | error                   |
|                           | `change_type` one of seven; status columns per type                                   | Port: `accepted_values`, `expression_is_true`            | error / warn            |
|                           | store, device, type copied from the incident                                          | By construction                                          | —                       |
|                           | not before the incident's time (DQ27); latest status matches (DQ28)                   | Port: singular tests                                     | warn                    |
| **All tables**            | id not already in BigQuery (`--check-db`)                                             | Not applicable: incremental `merge` on the key, plus `unique` | —                  |

**Not in this table:** the checks POC 1 only reported and never applied (DQ16, DQ20, DQ22–DQ24, DQ26, DQ30–DQ32).
They are defined in the POC 1 schema document. Review them with the POC C owner before porting.

### 4.4 Other required checks

| Check                             | Layer | Mechanism                                                     | Severity  | Task, test |
| --------------------------------- | ----- | ------------------------------------------------------------- | --------- | ---------- |
| Source freshness, every source    | ①     | `freshness` blocks, values from `entity_registry`             | warn / error | C12, AT-32 |
| Source key not null               | ①     | `not_null` on each source's key                               | error     | Proposed   |
| One row per key in staging        | ②     | `unique` on each `stg_*` key                                  | error     | A10, AT-15 |
| Tenant on every tenant-scoped row | ④     | `not_null` on `tenant_id`, **except** DQ37 stores (internal-only) | warn  | Proposed   |
| Customer definition used once     | —     | B8 single-definition CI check covers `is_customer()`, `is_open_alert()` | error | C8, AT-19 |
| Golden store-health scenarios     | ⑤     | Singular test against `seeds/golden_store_health.csv`         | error     | C6, AT-26b |
| Older change does not overwrite   | ③/④   | dbt unit test on `fct_alert`                                  | error     | AT-18      |
| Quarantine is visible             | ③     | Custom generic test `dq_quarantine_count`                     | warn above 0, error above 5% | Proposed |
| Native view equals its dbt version | ⑤    | Singular test or a parity script                              | error     | C11, AT-34 |

---

## 5. Implementation in dbt

Names follow the plan and the existing POC C guide. Column names come from the POC 1 stage models
(`app/models/stage/tables/`), renamed as in Appendix A (`created_at` becomes `opened_at`). **They are placeholders
until the staging models exist.**

### 5.1 Project settings (`dbt_project.yml`, plan 0.4)

```yaml
models:
  poc_dwh:
    staging:      {+schema: stg,   +materialized: view}
    intermediate: {+schema: prep,  +materialized: table}
    marts:        {+schema: build, +contract: {enforced: true}}
    rollups:      {+schema: build, +contract: {enforced: true}}
    security:     {+schema: build}

data_tests:
  poc_dwh:
    +store_failures: true      # failing rows saved in dq_{env}
    +schema: dq
    +severity: error           # default; warnings are set per test

vars:
  future_tolerance_minutes: 5
  pii_deny_columns: ['email', 'phone', 'first_name', 'last_name', 'user_name', 'contact_name']
  pii_allow_columns: ['store_name', 'account_name', 'assignee_team_name']
  quarantine_error_pct: 5      # Proposed
```

```yaml
# packages.yml
packages:
  - package: dbt-labs/dbt_utils
    version: [">=1.1.0", "<2.0.0"]
  - package: metaplane/dbt_expectations
    version: [">=0.10.0", "<0.11.0"]
```

### 5.2 Sources: freshness and key tests (①, C12, DQ40)

```yaml
# models/sources/sources_crm.yml
sources:
  - name: raw_crm
    schema: raw_crm
    loaded_at_field: _loaded_at
    freshness:                                   # values from entity_registry (E7)
      warn_after:  {count: 60, period: minute}
      error_after: {count: 75, period: minute}   # DQ40
    tables:
      - name: account
        columns:
          - name: account_id
            data_tests: [not_null]
```

The plan runs `dbt source freshness` as **warn only** in the micro-batch. The alert itself comes from
`freshness_check` (E7).

### 5.3 Staging: current row per key, dedup (②, DQ35)

```sql
-- models/staging/g2/stg_g2__alert_incidents.sql
{{ cdc_current_state(source('raw_g2', 'g2_alert_incidents'), ['incident_id']) }}
```

```sql
-- models/staging/lpos/stg_lpos__case_event.sql   (DQ35: keep one row per event_id)
select * from {{ source('raw_lpos', 'case_event') }}
qualify row_number() over (partition by event_id order by publish_time desc) = 1
```

```sql
-- tests/dq35_duplicate_case_events.sql   (reports how many duplicates were removed)
{{ config(severity='warn', tags=['dq', 'dq35']) }}
select event_id, count(*) as copies
from {{ source('raw_lpos', 'case_event') }}
group by event_id
having count(*) > 1
```

### 5.4 Row rules: `int_alert__validated` (③, DQ33, DQ34, DQ38)

```sql
-- models/intermediate/alert/int_alert__validated.sql
with incidents as (
  select * from {{ ref('stg_g2__alert_incidents') }}
),
checked as (
  select
    i.*,
    array_concat(
      if(s.store_id      is null, ['DQ33_UNKNOWN_STORE'],      []),
      if(d.device_id     is null, ['DQ33_UNKNOWN_DEVICE'],     []),
      if(t.alert_type_id is null, ['DQ33_UNKNOWN_ALERT_TYPE'], []),   -- Proposed (POC 1 UNKNOWN_REFERENCE)
      if(greatest(i.opened_at, coalesce(i.resolved_at, i.opened_at))
           > timestamp_add(timestamp('{{ run_started_at }}'),
                           interval {{ var('future_tolerance_minutes') }} minute),
         ['DQ34_FUTURE_TIME'], []),
      if(i.resolved_at < i.opened_at, ['DQ38_RESOLVED_BEFORE_OPEN'], [])
    ) as _dq_reasons
  from incidents as i
  left join {{ ref('stg_g2__stores') }}           as s on s.store_id      = i.store_id
  left join {{ ref('stg_g2__device_locations') }} as d on d.device_id     = i.device_id
  left join {{ ref('stg_g2__alert_types') }}      as t on t.alert_type_id = i.alert_type_id
)
select
  *,
  if(array_length(_dq_reasons) = 0, 'PASS', 'QUARANTINE') as _dq_status
from checked
```

- **Why `run_started_at` and not `current_timestamp()`:** every model in one run then uses the same "now". This
  matches POC 1's "as-of" time ([validation-rules.md](../../data-lake-ETL-tool/docs/validation-rules.md),
  "As of" time).
- **All reasons are kept,** as in POC 1, which rejected a row "with every reason found".

```sql
-- models/intermediate/alert/quarantine_alert.sql
{{ config(schema='dq', materialized='table') }}
select *, timestamp('{{ run_started_at }}') as _dq_checked_at
from {{ ref('int_alert__validated') }}
where _dq_status = 'QUARANTINE'
```

```sql
-- models/marts/core/fct_alert.sql  (shortened)
{{ config(partition_by={'field': 'alert_date', 'data_type': 'date'},
          cluster_by=['tenant_id', 'store_id', 'device_id']) }}
select ...
from {{ ref('int_alert__validated') }} as i
where i._dq_status != 'QUARANTINE'
```

**Warnings use the same pattern, but keep the row.**

DQ36 (unknown account type):

```sql
-- in dim_account.sql
coalesce(m.customer_type, 'UNKNOWN') as customer_type     -- type code not in seed map_customer_type
```

DQ37 (store with no tenant):

```sql
-- in int_store__tenant.sql
crm.tenant_id                                                -- stays null when there is no active CRM store
```

### 5.5 Model tests in `.yml` (④, C1, DQ36, DQ43)

```yaml
# models/marts/core/fct_alert.yml
models:
  - name: fct_alert
    description: One row per alert incident. Quarantined rows removed; soft deletes kept.
    config:
      contract: {enforced: true}
      meta: {primary_key: incident_id}            # read by the C1 CI check (5.9)
    data_tests:
      - dbt_utils.expression_is_true:             # POC 1: alert_id = ALR-<device>-<type>
          expression: "alert_id = concat('ALR-', device_id, '-', alert_type_id)"
          config: {severity: warn, tags: ['dq']}
    columns:
      - name: incident_id
        data_type: string
        description: Source incident key, e.g. INC910101.
        data_tests: [unique, not_null]
      - name: store_id
        data_type: string
        description: Store of the incident.
        data_tests:
          - not_null
          - relationships: {to: ref('dim_store'), field: store_id}
      - name: status_id
        data_type: string
        description: Current status; one of the seven in seed status.
        data_tests:
          - relationships: {to: ref('status'), field: status_id}
      - name: priority
        data_type: string
        description: P1 to P5.
        data_tests:
          - accepted_values: {values: ['P1', 'P2', 'P3', 'P4', 'P5']}
      - name: tenant_id
        data_type: string
        description: Top-level CRM account; null for internal-only stores (DQ37).
```

```yaml
# models/marts/wheel/fct_wheel_event.yml   (DQ43: kept, flagged)
      - name: wheel_id
        data_tests:
          - relationships:
              to: ref('dim_wheel')
              field: wheel_id
              config: {severity: warn, tags: ['dq', 'dq43']}
```

```yaml
# models/marts/crm/dim_account.yml   (DQ36: count of UNKNOWN types)
      - name: customer_type
        data_tests:
          - accepted_values:
              values: ['CUSTOMER', 'VENDOR', 'PARTNER', 'PROSPECT']
              config: {severity: warn, tags: ['dq', 'dq36']}
```

**Big facts:** to keep the cost of incremental runs down, limit expensive tests to recent partitions:

```yaml
config: {where: "alert_date >= date_sub(current_date(), interval 3 day)"}
```

The daily full load runs them without the filter.

### 5.6 Making quarantine visible (Proposed)

A quarantined row doesn't fail anything, so without this test a broken source could empty `fct_alert` silently.

```sql
-- tests/generic/dq_quarantine_count.sql
{% test dq_quarantine_count(model, column_name) %}
select {{ column_name }} as reason, count(*) as rows_quarantined
from {{ model }}, unnest(_dq_reasons) as {{ column_name }}
where _dq_status = 'QUARANTINE'
group by 1
{% endtest %}
```

```yaml
# models/intermediate/alert/int_alert__validated.yml
models:
  - name: int_alert__validated
    data_tests:
      - dq_quarantine_count:
          column_name: reason
          config: {severity: warn, tags: ['dq', 'quarantine']}
```

**Proposed:** also add an `error` singular test for when more than `var('quarantine_error_pct')` per cent of
incidents are quarantined. The planted rate is about 0.5% (plan section 13).

### 5.7 Singular tests (⑤, ⑥, POC 1 cross-row rules)

```sql
-- tests/dq41_no_personal_data_columns.sql   (C9, AT-28)
{{ config(severity='error', tags=['dq', 'dq41']) }}
select table_name, column_name
from `{{ target.project }}`.`{{ generate_schema_name('build', none) }}`.INFORMATION_SCHEMA.COLUMNS
where lower(column_name) in (
        {%- for c in var('pii_deny_columns') %}'{{ c }}'{% if not loop.last %}, {% endif %}{% endfor -%})
  and lower(column_name) not in (
        {%- for c in var('pii_allow_columns') %}'{{ c }}'{% if not loop.last %}, {% endif %}{% endfor -%})
```

```sql
-- tests/golden_store_health.sql   (C6, AT-26b)
{{ config(severity='error', tags=['golden']) }}
select g.store_id, g.expected_colour, h.health_colour, g.expected_reason, h.reason
from {{ ref('golden_store_health') }} as g
left join {{ ref('mv_store_health') }} as h using (store_id)
where h.store_id is null
   or g.expected_colour != h.health_colour
   or g.expected_reason != h.reason
```

```sql
-- tests/poc1_dq13_resolved_matches_closed_status.sql   (POC 1 DQ13, warn)
{{ config(severity='warn', tags=['dq', 'poc1']) }}
select a.incident_id, a.resolved_at, s.is_closed
from {{ ref('fct_alert') }} as a
join {{ ref('status') }}    as s using (status_id)
where not a.is_deleted
  and (a.resolved_at is not null) != s.is_closed
```

```sql
-- tests/poc1_dq29_overlapping_incidents.sql   (POC 1 DQ29, warn)
{{ config(severity='warn', tags=['dq', 'poc1']) }}
select a.alert_id, a.incident_id, b.incident_id as overlaps_with
from {{ ref('fct_alert') }} as a
join {{ ref('fct_alert') }} as b
  on a.alert_id = b.alert_id and a.incident_id < b.incident_id
where not a.is_deleted and not b.is_deleted
  and a.opened_at < coalesce(b.resolved_at, timestamp '9999-12-31')
  and b.opened_at < coalesce(a.resolved_at, timestamp '9999-12-31')
```

The singular tests for DQ08, DQ25, DQ27, DQ28 and the device-type match follow the same shape. Name each one
`poc1_dqNN_<rule>.sql` so it can't be confused with the new DQ33–DQ43 (issue 2).

### 5.8 Unit test (AT-18: an older change doesn't overwrite a newer one)

```yaml
# models/marts/core/fct_alert.yml
unit_tests:
  - name: older_change_is_ignored
    model: fct_alert
    overrides:
      macros: {is_incremental: true}
    given:
      - input: this
        rows:
          - {incident_id: INC1, current_status: 'Resolved', _source_updated_at: '2026-11-20 10:00:00'}
      - input: ref('int_alert__validated')
        rows:
          - {incident_id: INC1, current_status: 'Not Started', _source_updated_at: '2026-11-20 09:00:00', _dq_status: PASS}
    expect:
      rows:
        - {incident_id: INC1, current_status: 'Resolved'}
```

### 5.9 C1 convention check in CI (⑦, AT-36)

A small script reads `target/manifest.json` after `dbt parse`. It fails the pull request if a `build` model breaks
the rules in 4.1.

```python
# scripts/ci/check_dbt_conventions.py   (Proposed)
import json, sys

manifest = json.load(open("dbt/target/manifest.json"))
nodes = manifest["nodes"].values()
tests_on = {}                                   # (model, column) -> set of test names
for t in (n for n in nodes if n["resource_type"] == "test"):
    name = t["test_metadata"]["name"] if t.get("test_metadata") else None
    for parent in t["depends_on"]["nodes"]:
        tests_on.setdefault((parent, t.get("column_name")), set()).add(name)

errors = []
for m in (n for n in nodes if n["resource_type"] == "model" and n["config"]["schema"] == "build"):
    key = m["config"].get("meta", {}).get("primary_key")
    if not key:
        errors.append(f"{m['name']}: no meta.primary_key")
    elif isinstance(key, str) and not {"unique", "not_null"} <= tests_on.get((m["unique_id"], key), set()):
        errors.append(f"{m['name']}.{key}: needs unique and not_null")
    for col, spec in m["columns"].items():
        if not spec.get("description"):
            errors.append(f"{m['name']}.{col}: no description")
    if not m["config"].get("contract", {}).get("enforced"):
        errors.append(f"{m['name']}: contract not enforced")

print("\n".join(errors) or "conventions OK")
sys.exit(1 if errors else 0)
```

A composite key (a list) is checked for `unique_combination_of_columns` in the same way.

---

## 6. The validation flow: from rule to review

```
1 WRITE      2 RUN LOCALLY      3 PROVE IT CATCHES      4 CI            5 SCHEDULED RUN       6 REVIEW            7 ACT
rule/test →  dbt build       →  plant a defect,      →  PR blocked   →  micro-batch:       →  run_results,    →  fix source/model,
in .sql/.yml --target local     check it fails          if it fails     build → publish      dq_{env} tables     or accept warning
```

### Step 1: write the rule

1. Pick the mechanism (section 2.1). Ask: **must the row be kept out?**
   - **Yes:** row rule in `int_*__validated`.
   - **No:** test.
2. Pick the severity:
   - **critical** = quarantine;
   - **error** = stop publishing;
   - **warn** = report only.
3. Write it in the right place:
   - a column rule goes in the model's `.yml` (one `.yml` per model, as the dbt README requires);
   - a cross-table rule goes in `tests/dqNN_<name>.sql` or `tests/poc1_dqNN_<name>.sql`.
4. Tag it: `dq`, `dqNN` and `critical`, `error` or `warn`.
5. Add it to the catalogue in section 4 of this document.

### Step 2: run it locally

```bash
cd dbt
dbt deps                                              # installs dbt_utils, dbt_expectations
dbt build --target local --select +fct_alert          # build the model and its parents, with all their tests
dbt test  --target local --select fct_alert           # tests only, on already-built tables
dbt test  --target local --select tag:dq41            # one check
dbt test  --target local --select test_type:singular  # all singular tests
dbt source freshness --target local                   # freshness only
dbt compile --select dq41_no_personal_data_columns    # see the SQL a test runs (target/compiled/...)
```

Local builds go to `dbt_<you>_*` datasets, never to `build_dev` (dbt README).

### Step 3: prove the check catches the defect (C7 "done when")

| Check            | How to plant the defect                                         |
| ---------------- | --------------------------------------------------------------- |
| DQ33, DQ34, DQ38 | Simulator batch 3, and the continuous mode (plan section 13)    |
| DQ35             | About 2% duplicate case events from the simulator               |
| DQ36             | One unknown type code in every CRM export                       |
| DQ37             | Two seed stores with no CRM store                               |
| DQ41             | A test pull request that adds an `email` column; CI must fail   |
| DQ43             | About 0.5% unknown wheels                                       |
| POC 1 rules      | A unit test, or a seed fixture with one bad row per rule         |

Expected result: each planted defect appears in `quarantine_alert` or in its test's failing rows, **and nowhere
else**.

### Step 4: CI on the pull request (AT-36)

1. `dbt parse`, then `check_dbt_conventions.py` (C1).
2. `dbt build --target ci` into `dbt_pr_<n>_*` datasets, which expire after one day.
3. Any `error` test failure blocks the merge. Warnings show in the log.

### Step 5: the scheduled run (plan, section 8 of the POC C guide)

| Run                  | Validation steps                                                                                         |
| -------------------- | -------------------------------------------------------------------------------------------------------- |
| Micro-batch (dev every 15 minutes, int hourly) | `dbt source freshness` (warn only) → `dbt build --exclude tag:daily` with all tests → `publish.py` **only if exit code 0** → `freshness_check` |
| Daily full rebuild (20:15 on weekdays) | `dbt build --full-refresh` with all tests unfiltered → DQ39 comparison → `publish.py --all` → personal-data value scan (DQ41) |

### Step 6: review the results

| Where                                  | What you see                                                                 |
| -------------------------------------- | ---------------------------------------------------------------------------- |
| Console / Cloud Run log                | `PASS`, `WARN`, `ERROR`, `SKIP` per test, with the failure count              |
| `target/run_results.json`              | The same, as data: `unique_id`, `status`, `failures`, `execution_time`       |
| `dq_{env}.<test name>`                 | The failing rows of each test (`store_failures`). Replaced on every run      |
| `dq_{env}.quarantine_alert`            | Every quarantined incident, with `_dq_reasons`                               |
| `ops_{env}`                            | Workflow step log; `PUBLISH_SKIPPED` when dbt failed; DQ39 results in `dq_result` |
| `dbt docs generate && dbt docs serve`  | Every model, its tests and the lineage graph                                 |

Useful review queries:

```sql
-- quarantined incidents by reason
select reason, count(*) as n
from `dq_dev.quarantine_alert`, unnest(_dq_reasons) as reason
group by reason order by n desc;

-- one test's failing rows
select * from `dq_dev.unique_fct_alert_incident_id` limit 100;
```

**Proposed:** the `store_failures` tables are overwritten on each run, so keep a history of results. Add an
`on-run-end` hook that writes each test's status and failure count from `results` into `ops_{env}.dq_result`.
DQ39 already writes there.

### Step 7: act on the result

| Result                                  | What it means                                       | Who acts                                     |
| --------------------------------------- | --------------------------------------------------- | -------------------------------------------- |
| `ERROR`                                 | Nothing was published. `wh_{env}` keeps the last good version. Alert email sent | Model owner: fix the model, or the source owner fixes the data |
| `WARN`                                  | Published. Count recorded                           | Check owner reviews the trend; it becomes `error` if it grows |
| Quarantine count above 0                | Bad source rows kept out                            | Source owner (POC A for G2), using `_dq_reasons` |
| Quarantine above `quarantine_error_pct` | Probably a broken source or a broken rule           | Stop and investigate before the next publish |
| Freshness error                         | Source stopped                                      | Source owner; the `freshness_check` alert     |

---

## 7. Severity policy (Proposed, consistent with the plan)

| Level        | Use it when                                                        | dbt form                         | Effect on publish             |
| ------------ | ------------------------------------------------------------------ | -------------------------------- | ----------------------------- |
| **Critical** | One bad row would make a published answer wrong                   | Row rule → quarantine            | The row is left out; publish goes on |
| **Error**    | The table as a whole is wrong: duplicate keys, broken contract, personal data, wrong golden result | Test, `severity: error` | Publish stops              |
| **Warn**     | Worth knowing, but readers' answers are still right                | Test, `severity: warn`           | Publish goes on               |

---

## 8. Acceptance tests these validations serve

| AT    | What it needs from this work                                                  |
| ----- | ----------------------------------------------------------------------------- |
| AT-15 | One row per key in each `stg_g2__*` (②)                                       |
| AT-17 | Incremental equals full rebuild; `unique` on fact keys                        |
| AT-18 | The unit test in 5.8; soft deletes kept                                       |
| AT-19 | `is_customer()` defined once (C8, B8)                                         |
| AT-22 | DQ35 duplicates counted once                                                   |
| AT-26 | Parity and the golden test (5.7)                                              |
| AT-28 | DQ41 on every build, plus the daily value scan                                |
| AT-32 | Source freshness (5.2)                                                        |
| AT-33 | Every story table built **with tests** (4.1)                                  |
| AT-36 | CI blocks a failing dbt test (5.9, 6 step 4)                                  |

---

## 9. Issues to settle

1. **Implementation guide missing.** The plan points to section 8.6 of `bigquery-warehouse-implementation.md` for
   the porting method. That file is not in any local repo. Ask the plan owner for it, then align this document.
2. **DQ34 means two things.** POC 1 [validation-rules.md](../../data-lake-ETL-tool/docs/validation-rules.md)
   uses DQ34 for "device type equals the alert type's device type". The plan's new DQ34 is "event time in the
   future". **Proposed:** name POC 1 checks `poc1_dqNN` in files and tags.
3. **"Enforced at source" may not be true for formats.** The plan's C7 note says PostgreSQL enforces types and
   formats, but task 0.5 creates "primary keys on every table, no foreign keys" and doesn't mention `CHECK`
   constraints. Types are enforced; patterns (`H` + 7 digits, `D` + 3 digits, ISO country) are not, unless 0.5
   adds them. Confirm with the POC A owner, or port them as warn regex tests.
4. **Unknown alert type.** DQ33 covers device and store only. POC 1 also rejected an unknown alert type.
   **Proposed:** add `DQ33_UNKNOWN_ALERT_TYPE` to the same rule.
5. **History of a quarantined incident.** POC 1 rejected the incident's history too (`UNKNOWN_REFERENCE`). If
   `fct_alert_history` keeps those events, its `relationships` test to `fct_alert` fails and stops the publish.
   **Proposed:** `fct_alert_history` keeps only events whose incident is in `fct_alert`, and sends the rest to
   `dq_{env}.quarantine_alert_history`.
6. **POC 1 rejections that become warnings.** POC 1 rejected DQ08, DQ25, DQ27, DQ28, DQ29 and DQ13. The plan's
   quarantine list is only DQ33, DQ34 and DQ38. I've proposed **warn** for the rest. In particular, devices now
   move between stores, so DQ08 must not quarantine. Agree this with the POC C owner.
7. **Test cost on large facts.** Every micro-batch runs every test on whole tables. Use `where` on recent partitions
   in the micro-batch, and unfiltered tests in the daily full load (5.5).
8. **Results history.** The `store_failures` tables only hold the last run. Use the `on-run-end` hook into
   `ops_{env}.dq_result` (step 6).
9. **POC 1 report-only checks** (DQ16, DQ20, DQ22–DQ24, DQ26, DQ30–DQ32) are not defined in our repos. Decide with
   the POC C owner whether any are needed.
10. **Column names** in the code above are placeholders from the POC 1 stage models. Update them when the staging
    models are written.
