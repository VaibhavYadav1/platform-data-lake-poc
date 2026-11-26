# POC A critical path: from `raw_g2` to gate G6

**Written:** 24 Nov 2026 · **For:** whoever finishes A10 and A5 (Dev 3 / Dev 2 roles)  
**Covers:** close A4 → finish A10 (change-data staging) → run AT-15 for real (A5) → gate G6.  
**Design:** POC A guide sections 7.6 (AT-15) and 8 (current state), runbook phases 5 and 6; `docs/poc2/cdc.md`.

Every command and file in this document was rehearsed on 24 Nov in a throwaway dataset (`dbt_a10check_*`, since
deleted): the build passed 38/38, the unit tests pass with the fix and fail without it, and AT-15 passed 11/11.

---

## Why this is the critical path

POC A's job is to prove that a change in the G2 database reaches the warehouse quickly and correctly. A1–A4 proved
the first half: every change in Cloud SQL lands in `raw_g2` within about 6 seconds. But `raw_g2` is a **change
log**, not a table of current rows: one row per insert, update and delete. Nothing downstream can use it directly.

A10 turns the change log back into **one current row per key**, with deletes flagged. Everything after it waits on
that:

| Waits on A10 | Why |
| --- | --- |
| A5 / AT-15 → **gate G6** | AT-15 compares Cloud SQL with the staging views |
| A11 incremental facts → AT-18 | The fact merge reads one row per key from staging |
| A12 batch harness → AT-17 | Builds A11 after each batch |
| POC C dimensions (C2), validation (C7), tenant map (D3) | All read `stg_g2__*` |

Nothing blocks A10 itself, and most of it already exists. That's why it's first.

```
Stage 1  Close A4 (announce the parity snapshot)           10 min
Stage 2  Bring the dbt project and A10 onto main             1 h
Stage 3  Fix the two A10 defects                            1 h
Stage 4  Build and verify in your personal dataset          30 min
Stage 5  Commit A10 and tell the other teams                15 min
Stage 6  AT-15 for real → gate G6                           15 min
```

---

## Stage 1: Close A4

**Objective:** officially end the A3 data freeze.

**Why:** since A3, nobody may change G2 data, because the parity copy (`raw_g2_parity`) had to capture exactly the
POC 1 baseline. That copy exists now (10 tables, 2,160 rows), but the freeze only ends when the people waiting on it
are told. Dev 1 needs it to start the parity comparison (C4); Dev 3 needs it before any `batch` or `tick` touches
Cloud SQL. It's in the guide's runbook (phase 4) as its own step because a silent freeze blocks two people.

**Do:** send Dev 1 and Dev 3:

> Parity snapshot taken (A4, 24 Nov): `raw_g2_parity`, 10 tables, 2,160 rows, all backfill inserts. C4 may run
> against it (`--vars '{g2_raw_dataset: raw_g2_parity}'`). G2 may now be changed by the simulator. Never drop
> `raw_g2_parity`.

**Done when:** sent.

---

## Stage 2: Bring the dbt project and A10 onto `main`

**Objective:** a dbt project on `main` that can build the 11 `stg_g2__*` views.

**Why:** `main` has no dbt project yet (`dbt/` holds only READMEs; task 0.4 was never merged). The project
*does* exist on the branch **`origin/poc_c_dbt`** (POC C, Neha), together with A10's macro and all 11 views. That
is also where the 9 views in `dbt_dev_stg` came from. Building on an unmerged branch means AT-15 evidence that
nobody else can reproduce, so A10 has to land on `main`.

That branch has 132 changed files of POC C work. Merging all of it is POC C's decision, not A10's. So take **only
the files A10 needs**. Neha already merges `main` into her branch regularly; when she next does, the only files
that differ are the three you fix in stage 3, and she keeps `main`'s version.

### 2.1 Tell the branch owner first

Message Neha (POC C): "I'm bringing the dbt framework (0.4) and the A10 staging files from `poc_c_dbt` to `main`,
with two fixes to `cdc_current_state.sql`, `stg_g2__store_access.sql` and `stg_g2__models.yml`. When you merge `main`
into `poc_c_dbt`, take `main`'s version of those three."

**Why:** two people changing the same file on different branches is how merges go wrong. Saying it first costs a
minute.

### 2.2 Copy the files

```bash
cd /e/data-lake-POC/datalake-POC-phase2/platform-data-lake-poc
git checkout main && git pull
git fetch origin poc_c_dbt
git checkout origin/poc_c_dbt -- \
  dbt/dbt_project.yml dbt/profiles.yml dbt/packages.yml dbt/package-lock.yml \
  dbt/requirements.txt dbt/env.example \
  dbt/macros/generate_schema_name.sql dbt/macros/cdc_current_state.sql dbt/macros/log_dq_results.sql \
  dbt/models/sources/sources.yml \
  dbt/models/staging/g2
git status --short          # those files, staged; nothing else
```

What each file is for:

| File | Why A10 needs it |
| --- | --- |
| `dbt_project.yml` | The project: `staging` builds as views into the `stg` layer; the `g2_raw_dataset` var lets C4 point staging at `raw_g2_parity` |
| `profiles.yml` | How dbt logs in. `local` = you (OAuth), datasets `dbt_<DBT_USER>_*`; `dev`/`int` = the Cloud Run job later |
| `packages.yml`, `package-lock.yml` | `dbt_utils` (the two-column uniqueness test on `store_access`) |
| `requirements.txt` | dbt-core and dbt-bigquery 1.9, pinned so everyone runs the same version |
| `env.example` | Template for your `.env` (`DBT_USER`, `DBT_PROFILES_DIR`) |
| `generate_schema_name.sql` | Names datasets `dbt_<you>_stg` locally and `stg_dev` in dev, so a laptop never writes into shared datasets |
| `cdc_current_state.sql` | The A10 macro (fixed in stage 3) |
| `log_dq_results.sql` | `dbt_project.yml` calls it after every run (`on-run-end`); without it every run fails |
| `sources.yml` | Declares `raw_g2.g2_*` (and the other raw sources) as dbt sources |
| `models/staging/g2/*` | The 11 views and their tests |

Not copied, on purpose: POC C's intermediate, marts, rollups and security models, its other macros and seeds. They
belong to POC C's own merge.

### 2.3 Install dbt in its own environment

```bash
cd dbt
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/dbt --version             # dbt-core 1.9.x, bigquery 1.9.x
cp env.example .env                     # then edit DBT_USER to your short name, e.g. vaibhav
```

**Why a separate environment:** dbt pins its own versions of Google and protobuf libraries. Installing it into the
simulator's `.venv` can break the simulator. `dbt/.venv`, `.env`, `target/` and `dbt_packages/` are already in
`.gitignore`.

Load the settings in each new shell (Git Bash), then check the connection:

```bash
cd /e/data-lake-POC/datalake-POC-phase2/platform-data-lake-poc/dbt
set -a; source .env; set +a
export PYTHONUTF8=1                     # Windows: lets dbt print unit-test diffs (they contain "→")
.venv/Scripts/dbt deps                  # downloads dbt_utils, dbt_expectations
.venv/Scripts/dbt debug                 # every line OK, ends with "Connection test: OK"
```

**Why `dbt debug`:** it proves the three things that fail most often (project file, profile, BigQuery login)
before you build anything. It uses your `gcloud auth application-default` login.

**Done when:** `dbt debug` is all OK.

---

## Stage 3: Fix the two A10 defects

**Objective:** a macro that orders changes correctly and a build that doesn't fail on a missing raw table.

Building the branch as it is gives **32 passes and 1 error**, and the views it builds contain a latent ordering bug.

### Defect 1: changes are ordered as text

**What's wrong:** the macro breaks ties with `change_sequence_number` sorted as text. A4 found that this field is
`<hex time>/<LSN high>/<LSN low>` **without zero-padding** (`cdc.md` 4.5): `'…/0/ffffff'` sorts *after*
`'…/0/1000000'`, although the second is the later WAL position.

**Why it matters:** when two changes to the same key share a millisecond (common in a busy tick, or a batch's
"update twice" step), the older one can win. The staging row then shows stale values, and A11's merge would write
them into `fct_alert`. Today's data doesn't show it (WAL positions are still 7 hex digits), so it would pass every
test now and fail weeks later. The WAL grows constantly, so the digit change will come.

**Fix:** order by `source_timestamp`, then the LSN from `sort_keys[1]` parsed from hex into numbers. A backfill row
has no LSN (`""` → NULL) and loses a tie, which is right: a change event with the same timestamp is at least as new.

### Defect 2: `stg_g2__store_access` fails to build

**What's wrong:** Datastream creates no BigQuery table for a source table with no rows. `g2.store_access` is empty
until the tenant model exists (task 0.7), so `raw_g2.g2_store_access` doesn't exist and the view can't be created:
`Not found: Table …raw_g2.g2_store_access`.

**Why it matters:** a failing view fails `dbt build`, which later fails every micro-batch (E3). AT-15 can't pass
with a missing view, and POC C's `map_tenant_access` reads it.

**Fix:** the model declares its columns. When the raw table is missing, the macro builds an **empty view with the
right column types** instead. Once the first `simulator grant` creates the raw table, the next `dbt build` reads the
real change log automatically. (Don't pre-create the raw table in Terraform: Datastream must create it with its own
metadata columns.)

### 3.1 Replace `dbt/macros/cdc_current_state.sql`

```sql
{#
  A10: current state per key from Datastream's append-only change log (docs/poc2/cdc.md, A4).

  - Newest change per key decides is_deleted / deleted_at / _source_updated_at.
  - Newest non-delete change supplies the column values (a DELETE row carries only the key).
  - Order: source_timestamp, then the WAL position (LSN) from sort_keys[1], parsed from hex.
    change_sequence_number is NOT used: it isn't zero-padded, so it doesn't sort as text (cdc.md 4.5).
    Backfill rows have no LSN (NULL here) and lose a tie against a change with the same timestamp.
  - empty_columns: {column: BigQuery type} for a source table that may not exist yet. Datastream creates no table
    for an empty source table (g2_store_access until its first row); without this the build fails. The view is then
    empty but typed, and the next dbt build after the table appears reads the real change log.
#}
{% macro cdc_current_state(source_relation, key_columns, empty_columns=none) %}
{%- set keys = key_columns | join(', ') -%}
{%- set newest_first = '_source_updated_at desc, _lsn_hi desc nulls last, _lsn_lo desc nulls last' -%}
{%- set source_exists = true -%}
{%- if execute and empty_columns is not none -%}
  {%- set source_exists = adapter.get_relation(
        database=source_relation.database,
        schema=source_relation.schema,
        identifier=source_relation.identifier) is not none -%}
{%- endif -%}
{%- if not source_exists %}
-- {{ source_relation }} doesn't exist yet (no rows in the source table): typed, empty
select
  {%- for column, data_type in empty_columns.items() %}
  cast(null as {{ data_type }}) as {{ column }},
  {%- endfor %}
  cast(null as bool)      as is_deleted,
  cast(null as timestamp) as deleted_at,
  cast(null as timestamp) as _source_updated_at
from unnest([1])
where false
{%- else %}
with changes as (
  select
    t.* except (datastream_metadata),
    timestamp_millis(t.datastream_metadata.source_timestamp) as _source_updated_at,
    t.datastream_metadata.change_type = 'DELETE'             as _is_delete,
    safe_cast(concat('0x', split(nullif(t.datastream_metadata.sort_keys[safe_offset(1)], ''), '/')[safe_offset(0)]) as int64) as _lsn_hi,
    safe_cast(concat('0x', split(nullif(t.datastream_metadata.sort_keys[safe_offset(1)], ''), '/')[safe_offset(1)]) as int64) as _lsn_lo
  from {{ source_relation }} as t
),
latest_change as (   -- the newest change of any kind
  select {{ keys }}, _is_delete as is_deleted, _source_updated_at
  from changes
  qualify row_number() over (partition by {{ keys }} order by {{ newest_first }}) = 1
),
latest_image as (    -- the newest full row; a DELETE row may carry only the key
  select * except (_is_delete, _source_updated_at, _lsn_hi, _lsn_lo)
  from changes
  where not _is_delete
  qualify row_number() over (partition by {{ keys }} order by {{ newest_first }}) = 1
)
select
  i.* except (updated_at),
  c.is_deleted,
  if(c.is_deleted, c._source_updated_at, null) as deleted_at,
  c._source_updated_at
from latest_change as c
join latest_image as i using ({{ keys }})
{%- endif %}
{% endmacro %}
```

How it works, block by block:

| Block | What it does | Why |
| --- | --- | --- |
| `changes` | Every change row, with three plain helper columns: source time, "is a delete", and the LSN as two numbers | Window functions can't sort on a hex string correctly; numbers sort correctly |
| `latest_change` | Per key, the newest change of any kind | Decides whether the key is deleted now, and when it last changed |
| `latest_image` | Per key, the newest change that isn't a delete | A delete row has only the key (A2: replica identity default); the last full row supplies the values |
| final join | One row per key: values from `latest_image`, flags from `latest_change` | Soft delete: the key stays, flagged, with its last values. A11 needs that to mark facts deleted instead of losing them |
| `except (updated_at)` | Drops the source's own `updated_at` | Kept from the branch: `_source_updated_at` is the time that counts downstream; no G2 model uses `updated_at` |
| `if not source_exists` | Typed empty view | Defect 2. Only checked when a model passes `empty_columns`, so the other 10 views never pay for the lookup |

The view reads the whole change log every time it's queried. At POC volume (thousands of rows a day) that's cheap,
and it means a change that arrives late still lands in the right place (guide 8.1).

### 3.2 Replace `dbt/models/staging/g2/stg_g2__store_access.sql`

```sql
-- Current state per key from the append-only change stream (A10).
-- raw_g2.g2_store_access exists only after the first grant (Datastream creates no table for an empty source table),
-- so the columns are declared for the empty fallback (types as in sql/g2/schema.sql; updated_at is dropped by the macro).
{{ cdc_current_state(
    source('raw_g2', 'g2_store_access'),
    ['principal', 'crm_account_id'],
    empty_columns={'principal': 'string', 'crm_account_id': 'string', 'granted_at': 'timestamp'}
) }}
```

**Why these columns:** they're `g2.store_access`'s columns in `sql/g2/schema.sql`, minus `updated_at`, which the macro
drops. When the real table appears, the view has the same shape, so nothing downstream notices the switch.

### 3.3 Add unit tests to the end of `dbt/models/staging/g2/stg_g2__models.yml`

```yaml

# A10 rules, proved on fixtures (heartbeat has few columns, and format: sql fixtures must list every column).
unit_tests:
  - name: stg_g2__heartbeat__delete_keeps_last_image
    description: The newest change is a DELETE, so the key is flagged and keeps the values of its last full row.
    model: stg_g2__heartbeat
    given:
      - input: source('raw_g2', 'g2_heartbeat')
        format: sql
        rows: |
          select 'cdc-test' as source, timestamp '2026-11-24 08:48:11' as beat_at, timestamp '2026-11-24 08:48:11' as updated_at,
                 struct('u1' as uuid, 1795510091157 as source_timestamp, '1a20cbdbd95/0/24eef48' as change_sequence_number,
                        'INSERT' as change_type, ['1795510091157', '0/24EEF48'] as sort_keys) as datastream_metadata
          union all
          select 'cdc-test', timestamp '2026-11-24 08:49:28', timestamp '2026-11-24 08:49:28',
                 struct('u2', 1795510168716, '1a20cbeec8c/0/24f3648', 'UPDATE', ['1795510168716', '0/24F3648'])
          union all
          select 'cdc-test', cast(null as timestamp), cast(null as timestamp),
                 struct('u3', 1795510185598, '1a20cbf2e7e/0/24f3770', 'DELETE', ['1795510185598', '0/24F3770'])
    expect:
      rows:
        - {source: cdc-test, beat_at: "2026-11-24 08:49:28", is_deleted: true, deleted_at: "2026-11-24 08:49:45.598"}

  - name: stg_g2__heartbeat__lsn_order_not_text_order
    description: >
      Two changes in the same millisecond. As text '0/1000000' sorts before '0/FFFFFF', but it is the later WAL
      position, so its row must win (cdc.md 4.5).
    model: stg_g2__heartbeat
    given:
      - input: source('raw_g2', 'g2_heartbeat')
        format: sql
        rows: |
          select 'simulator' as source, timestamp '2026-11-24 10:00:00' as beat_at, timestamp '2026-11-24 10:00:00' as updated_at,
                 struct('u1' as uuid, 1795600000000 as source_timestamp, '1a213e5d800/0/ffffff' as change_sequence_number,
                        'UPDATE' as change_type, ['1795600000000', '0/FFFFFF'] as sort_keys) as datastream_metadata
          union all
          select 'simulator', timestamp '2026-11-24 10:00:01', timestamp '2026-11-24 10:00:01',
                 struct('u2', 1795600000000, '1a213e5d800/0/1000000', 'UPDATE', ['1795600000000', '0/1000000'])
    expect:
      rows:
        - {source: simulator, beat_at: "2026-11-24 10:00:01", is_deleted: false}
```

**Why unit tests and not just data tests:** data tests check today's data, and today's data can't show either rule
(the LSNs are still short). A unit test feeds the model hand-made rows and checks the answer, so it proves the
*logic*.
- The first is the guide's delete test (8.5), using the real `cdc-test` rows from A4.
- The second is exactly the case where text order breaks. Run against the branch's original macro it **fails**
  ("expected 10:00:01, actual 10:00:00"), so it's a real guard.

They use `stg_g2__heartbeat` rather than `stg_g2__alert_incidents` (the guide's example) because SQL fixtures must
list every source column, and heartbeat has 3, against incidents' 15. The macro is the same for every table.

**Done when:** the three files are changed; `git diff` shows only these three files differ from `poc_c_dbt`.

---

## Stage 4: Build and verify in your personal dataset

**Objective:** proof that the 11 views give one row per key, flag deletes and match Cloud SQL.

**Why your own dataset:** `--target local` builds into `dbt_<DBT_USER>_stg`. Never build into `stg_dev` from a laptop
(guide pitfall): `stg_dev` belongs to the dev runner (E3), and other people read it.

### 4.1 Build

```bash
.venv/Scripts/dbt build --target local --select path:models/staging/g2
```

`dbt build` creates the 11 views, then runs every test on them (25 data tests and 2 unit tests), in dependency order.

**Expect:** `Done. PASS=38 WARN=0 ERROR=0 SKIP=0 TOTAL=38`. `stg_g2__store_access` shows
`CREATE VIEW` (it's the typed empty one).

If a unit test fails, read the "actual differs from expected" diff: it shows the value it got against the one it
expected. If you see a `UnicodeEncodeError` instead, you forgot `export PYTHONUTF8=1`.

### 4.2 Check the results by eye

Replace `<you>` with your `DBT_USER`.

```sql
-- One row per key, and how many deletes (expect 450 rows, 450 keys, 0 deleted)
SELECT COUNT(*) AS n_rows, COUNT(DISTINCT incident_id) AS n_keys, COUNTIF(is_deleted) AS n_deleted
FROM `gks-datalake-poc2-dev.dbt_<you>_stg.stg_g2__alert_incidents`;

-- The A4 test row is flagged deleted, with its last full values (expect 2 rows)
SELECT source, beat_at, is_deleted, deleted_at
FROM `gks-datalake-poc2-dev.dbt_<you>_stg.stg_g2__heartbeat`;
--   cdc-test   2026-11-24 08:49:28  true   2026-11-24 08:49:45
--   simulator  <latest beat>        false  NULL

-- Empty but typed (expect 0)
SELECT COUNT(*) FROM `gks-datalake-poc2-dev.dbt_<you>_stg.stg_g2__store_access`;
```

**Why look:** tests check rules, and your eyes check meaning. `cdc-test` is the clearest example of a soft delete:
deleted at 08:49:45, still carrying its 08:49:28 values.

### 4.3 Rehearse AT-15 against your views

```bash
cd ..        # repo root; the Cloud SQL Auth Proxy must be running on port 5433
.venv/Scripts/python scripts/acceptance/at15_cdc_initial.py --stg-dataset dbt_<you>_stg
```

**Expect:** 11/11 OK, exit 0. **Delete the evidence file it writes** (`docs/poc2/evidence/at15_<time>.json`): this is
a rehearsal against a personal dataset, not the gate run.

**Done when:** 38/38 in 4.1, the expected values in 4.2, and 11/11 in 4.3.

---

## Stage 5: Commit A10 and tell the other teams

**Objective:** A10 on `main`, so dev, CI and POC C build from the same code.

```bash
cd /e/data-lake-POC/datalake-POC-phase2/platform-data-lake-poc
git status --short        # only dbt/ files; no .env, no dbt/.venv, no dbt/target
git add dbt
git commit -m "A10: dbt framework and change-data staging (cdc_current_state, 11 stg_g2 views)

- From poc_c_dbt: dbt_project/profiles/packages/requirements, generate_schema_name,
  log_dq_results, sources.yml, the 11 stg_g2 views and their tests (0.4 + A10)
- cdc_current_state: order by source_timestamp then the LSN from sort_keys,
  not change_sequence_number as text (cdc.md 4.5)
- Typed empty view when the raw table doesn't exist yet (g2_store_access)
- Unit tests: delete keeps the last image; LSN order beats text order
- Built locally: 38/38 pass; AT-15 rehearsal 11/11"
git push origin main
```

Then:
- **Neha / Dev 1 (POC C):** "A10 is on `main`. When you merge `main` into `poc_c_dbt`, take `main`'s
  `cdc_current_state.sql`, `stg_g2__store_access.sql` and `stg_g2__models.yml`. The 9 views in `dbt_dev_stg`
  still use the old ordering: rebuild them from `main` (or wait for the dev runner, E3)."
- **Record A10 in the POC A guide:** 17.0 row; phase 5 runbook "As built" (the two fixes, unit tests on
  heartbeat); section 21 "Staging change order" → Resolved; "Missing `g2_store_access`" → Resolved for A10/A5
  (still open for 0.7).

**Done when:** pushed; message sent; guide updated.

---

## Stage 6: AT-15 for real → gate G6

**Objective:** pass AT-15, which closes A5 and gate G6: *the first CDC copy is complete*.

**Why it's a gate:** G6 is the line between "data arrives" and "data is usable". It proves that every key in the
source reaches staging exactly once, with nothing lost and nothing duplicated, before anyone builds facts on it. After
G6, A11 and POC C can trust staging.

**Which staging dataset:** the guide's command takes "your personal `dbt_<you>_stg` on Day 5, or `stg_dev` once the
dev runner (E3) builds it". `stg_dev` doesn't exist yet, so use the one built **from `main`** in stage 4. Rebuild it
from `main` first, so the evidence matches committed code:

```bash
cd dbt && git pull && .venv/Scripts/dbt build --target local --select path:models/staging/g2 && cd ..
.venv/Scripts/python scripts/acceptance/at15_cdc_initial.py --stg-dataset dbt_<you>_stg
```

What the script does, and why each step is there:

| Step | Why |
| --- | --- |
| Pauses `poc-simulator-tick` (skipped until A8 exists), resumes it in `finally` | Counts must not move mid-check; `finally` restarts the simulator even if the script fails |
| Updates the `simulator` heartbeat and waits until it's in `raw_g2` | Proves Datastream has caught up. Counting earlier gives false failures |
| Counts each of the 11 tables in Cloud SQL and the non-deleted keys in staging | The definition of "first copy complete" |
| Writes evidence JSON, exits 0 only if all 11 match | The gate's proof, and something CI or `run_all.py` can act on |

**Expect:** 11/11 OK, exit 0.

Then:
```bash
git add docs/poc2/evidence/at15_*.json
git commit -m "A5: AT-15 passes against staging built from main (G6)"
git push origin main
```

and record it in the guide: 17.0 row (A5 done, G6), the 5.1/status columns, and the task table. Update
`docs/poc2/G2_CHANGE_PATH_STATUS.md` (A5 ✅, A10 ✅).

**Done when:** AT-15 evidence from `main`'s code is committed. **Gate G6 passed.**

---

## After G6

The critical path then splits:

| Next | Needs | Done when |
| --- | --- | --- |
| A11 incremental `fct_alert`, `fct_alert_history` | A10 ✅ and **C3** (POC C's plain-table facts) | AT-18: deletes are soft, change order respected |
| A12 batch harness | A11 | AT-17: incremental equals a full rebuild |
| A6 → A7 → A8 (case events, publisher, simulator in the cloud) | 0.7 for the Avro schema (`A6_STEPS.md`) | A8: runs every 5 minutes for 2 hours |
| AT-16 end-to-end latency → gate G7 | A8, A11, C5, C7, E5 | A change reaches store health in time |

## Rules that still hold

- Never `seed --reset` or re-seed Cloud SQL (the stream exists: old rows would arrive as deletes).
- Never drop `raw_g2_parity`.
- Never build into `stg_dev` from a laptop: `--target local`.
- Evening: pause the stream, then stop the database. Morning: the reverse.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `dbt debug`: profile not found | `DBT_PROFILES_DIR` not set | `set -a; source .env; set +a` in this shell |
| `dbt debug`: credentials error | No application-default login | `gcloud auth application-default login` |
| Build error `Not found: …g2_store_access` | Old macro or model still in place | Redo stage 3.1 and 3.2 |
| `UnicodeEncodeError` printing a unit test | Windows console | `export PYTHONUTF8=1` |
| `unique` test fails on a view | Wrong key list in the model | Keys must match guide 6.3; more than one row per key later breaks A11's merge |
| AT-15 times out waiting for the heartbeat | Stream paused or database stopped | `gcloud datastream streams describe poc-cdc-stream --location=us-central1 --format="value(state)"` → RUNNING |
| AT-15 `FAIL (view missing)` | Views not built in that dataset | Stage 4.1 with the same `DBT_USER` |
