# simulator

**Owner:** Dev 3  
**Tasks:** 0.6, A7, A8 (code), A9 (writer), B2

`poc-source-simulator`: keeps G2 (Cloud SQL), case events (Pub/Sub), CRM exports and `sim_g2_datalake` changing.
Scripted mode (`seed`, `batch --n 1..3`) for repeatable tests; continuous mode (`tick`) as a Cloud Run job every
5 minutes.

## Status

| Part | Task | State |
| --- | --- | --- |
| `seed`, `batch --n 1..3`, `expected/`, `tests/` | 0.6 | Done; verified on PostgreSQL 16 in Docker |
| `store_access` rows: `grant`, `revoke`, `store-access-seed` | D3, D6 (AT-25) | Done (offline tests); run on Cloud SQL after `seed` |
| Cloud SQL connection (`PG_INSTANCE`, `PG_SECRET`) | A3 / A8 | Not yet: use `PG_HOST` through the Auth Proxy |
| Case-event publisher | A7 | Not started |
| Dockerfile, `tick`, heartbeat, pause switch, `RATE` | A8 | Not started |
| `sim_g2_datalake` writer | A9 | Not started |
| CRM export writer | B2 | ✅ Done; generates hourly exports with change simulation |

## Run it locally

### G2 Database (seed and batch)

From the repository root, in Git Bash:

```bash
# 1. Python 3.12 environment (data-lake-schema comes from the Phase 1 Artifact Registry)
python -m venv .venv
.venv/Scripts/python -m pip install keyrings.google-artifactregistry-auth
.venv/Scripts/python -m pip install -r simulator/requirements-dev.txt

# 2. PostgreSQL 16 with the G2 schema
docker run -d --name g2pg -e POSTGRES_PASSWORD=local -p 5432:5432 postgres:16
psql "postgresql://postgres:local@localhost:5432/postgres" -c "CREATE DATABASE g2"
psql "postgresql://postgres:local@localhost:5432/g2" -v ON_ERROR_STOP=1 -f sql/g2/schema.sql

# 3. Seed, then the three batches (each compares itself with expected/batch_<n>.json)
export PG_HOST=localhost PG_PORT=5432 PG_DB=g2 PG_USER=postgres PG_PASSWORD=local
.venv/Scripts/python -m simulator seed --batch clean_data_20261116_190645
.venv/Scripts/python -m simulator batch --n 1
.venv/Scripts/python -m simulator batch --n 2
.venv/Scripts/python -m simulator batch --n 3

# 4. Tests (the database tests create and drop their own databases)
SIM_TEST_PG="host=localhost port=5432 user=postgres password=local" .venv/Scripts/python -m pytest simulator
```

### CRM Export Generator (B2)

Generate CRM exports locally:

```bash
# Generate 3 hourly exports to local directory
python -m simulator crm-export --local-dir ./test_crm_exports --count 3

# Generate exports with 10% change rate
python -m simulator crm-export --local-dir ./test_crm_exports --count 3 --change-rate 0.10

# Generate export with >50% change (for AT-21 testing)
python -m simulator crm-export --local-dir ./test_crm_exports --count 2 --big-change

# Generate exports with data quality issues planted
python -m simulator crm-export --local-dir ./test_crm_exports --count 1 --plant-issues

# Upload directly to GCS
python -m simulator crm-export --bucket gks-datalake-poc2-dev-crm --prefix crm --count 3

# Custom start time and seed
python -m simulator crm-export \
  --local-dir ./test_crm_exports \
  --count 3 \
  --start-time 20261120T080000Z \
  --seed 42
```

**Output structure:**
```
test_crm_exports/
  export_ts=20261120T080000Z/
    account.csv          (50 accounts with hierarchies)
    store.csv            (100 stores linked to accounts)
    work_order.csv       (work orders linked to accounts/stores/devices)
    manifest.json        (file metadata, written last)
  export_ts=20261120T090000Z/
    ...
```

If port 5432 is already taken (for example by a PostgreSQL installed on Windows), run the container with
`-p 5434:5432` and use port 5434 in every command above: otherwise `localhost:5432` reaches the other server.

Start again locally with `seed --batch ... --reset`. Never re-seed Cloud SQL once Datastream runs: the command
refuses `--reset` unless `PG_HOST` is a local name.

### Tenant access (D3, D6)

`seed` leaves `g2.store_access` empty. After seeding, add the POC D test rows once (re-running adds nothing):

```bash
.venv/Scripts/python -m simulator store-access-seed --dry-run      # print the rows
.venv/Scripts/python -m simulator store-access-seed                # tenant A/B users and apps, plus 2 proof rows
.venv/Scripts/python -m simulator revoke --principal <email> --account ACC00001   # AT-25: access removal
.venv/Scripts/python -m simulator grant  --principal <email> --account ACC00001   # and back
```

| Principal | Account | Proves |
| --- | --- | --- |
| `sa-tenant-a-user`, `sa-app-tenant-a` | `ACC00001` | Tenant A |
| `sa-tenant-b-user`, `sa-app-tenant-b` | `ACC00005` | Tenant B |
| `sa-tenant-a-user` | `ACC00002` (child of `ACC00001`) | Folds into tenant A; no new tenant |
| `sa-tenant-b-user` | `ACC00031` (vendor) | Dropped: a vendor is never a tenant |

Emails are `<name>@gks-datalake-poc2-dev.iam.gserviceaccount.com` (`--project` changes it).

## Settings (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `PG_HOST`, `PG_PORT` | none, `5432` | Server (localhost, or the Auth Proxy) |
| `PG_DB`, `PG_USER`, `PG_PASSWORD` | `g2`, `postgres`, none | Database and login |
| `PG_INSTANCE`, `PG_SECRET` | none | Cloud SQL connection name and password secret (A3/A8, not yet supported) |

## How it works

**`seed --batch <folder>`** loads the frozen POC 1 batch (`docs/poc2/baseline.md`) into an empty G2:

1. Checks the 11 tables of `sql/g2/schema.sql` exist with the expected columns.
2. Rebuilds the batch in memory with the vendored generator. The generator is deterministic (`SEED = 42`,
   `AS_OF = 2026-10-20`), so no file is read from the Phase 1 bucket. Every CSV's MD5 is checked against the
   batch's `manifest.json` (pinned in `baseline.py`); any difference stops the seed.
3. Loads the 9 tables with `COPY` in one transaction. Empty strings become NULL; PostgreSQL casts the text to
   `BOOLEAN` and `TIMESTAMPTZ`.
4. Adds the internal-only probe store `S999` with device `D999`, and the heartbeat row `simulator`.
5. Counts every table: the baseline counts plus the probe rows, or everything is rolled back.

**`batch --n 1|2|3`** applies one scripted change batch (plan 0.6). Each uses a fixed random seed, picks rows in key
order and stamps fixed times (`AS_OF` + n hours), so on a fresh seed every run makes the same changes. They run in
order, once each; the last step writes the heartbeat row `batch-<n>`.

| Batch | Changes | Result in `expected/` |
| --- | --- | --- |
| 1 | Insert 20 incidents (CREATED + ASSIGNED each: the plan's 40 history rows). Acknowledge 10 open incidents (Not Started or monitored -> In Review, one history row each) | 50 history rows |
| 2 | Close 15 open incidents. Delete 3 resolved POC 1 incidents and their 6 history rows. Move 1 device to another store | 15 history rows |
| 3 | Change 5 incidents twice (Case Opened, then Case Updated, in two transactions so CDC sees two commits). Re-open 2. Plant a future time (DQ34, year 2099), an unknown device (DQ33, `D990`) and resolved-before-opened (DQ38) | 16 history rows |

`expected/batch_<n>.json` holds the changed ids (`changes`) and the state after the batch (`state`): row counts,
open and closed incidents, and a fingerprint per table (MD5 of every row in key order, without `updated_at`,
`beat_at` and `granted_at`). After a batch, the command compares the database with the file and exits 1 on any
difference. `--write-expected` rewrites the file; do that only when a batch is changed on purpose, and review the
diff. AT-17 and AT-18 read these files.

**Interpretation, for review (Dev 2):** "acknowledged" is the generator's ASSIGNED step; every status change writes
a history row, so batch 1 writes 50, not 40.

## Layout

```
simulator/
  __main__.py, cli.py   command line
  config.py, db.py      settings and the one connection per command
  baseline.py           the frozen batch: name, row counts, MD5s, probe ids
  seed.py               seed
  batches.py            batch 1-3
  state.py              the state snapshot in expected/
  crm_export.py         CRM export generator (B2) ✅
  store_access.py       grant, revoke, store-access-seed (D3, D6)
  expected/             batch_1.json .. batch_3.json
  vendor/               POC 1's generator, unchanged (see vendor/README.md)
  tests/                pytest (includes test_crm_export.py)
```

## Files still to create here

| File | Task | Owner | Day | Notes |
| --- | --- | --- | --- | --- |
| `Case-event publisher` | A7 | Dev 3 | 4-5 | Planted duplicates |
| `Dockerfile, tick mode, heartbeat, pause switch, RATE` | A8 | Dev 3 (Dev 4: Terraform) | 5-6 | Cloud Run job `poc-source-simulator`, Scheduler `*/5 * * * *` |
| `sim_g2_datalake writer` | A9 | Dev 3 | 5-6 | `wheel_event` by load job, not streaming |
| ~~`CRM export writer`~~ | ~~B2~~ | ~~Dev 3~~ | ~~3-4~~ | ✅ **DONE** - `crm_export.py` generates hourly exports |

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".
