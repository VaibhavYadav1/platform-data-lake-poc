# CDC (tasks A2–A4)

**Owner:** Dev 2  
**Tasks:** A2 (source set-up), A4 (Datastream)  
**Date:** 24 Nov 2026  
**Status:** A4 complete. Verified 24 Nov against Cloud SQL, `raw_g2` and `raw_g2_parity` (see section 7 for corrections).

---

## 1. Source set-up (A2, 23 Nov 2026)

Applied to `poc-ops-db` by `scripts/g2_bootstrap.py` through the Auth Proxy.

| Object | State after A2 |
| --- | --- |
| `wal_level` | `logical` (flag `cloudsql.logical_decoding=on`, A1) |
| Publication `poc_pub` | All 11 `g2` tables |
| Slot `poc_slot` | `pgoutput`, logical. Inactive until A4; `active = t` since Datastream attached (24 Nov) |
| `datastream_user` | LOGIN, REPLICATION; SELECT on every `g2` table (and future ones, by default privileges) |
| `simulator_user` | LOGIN; SELECT, INSERT, UPDATE, DELETE on every `g2` table; no REPLICATION |
| Replica identity | Default (primary key): a delete carries only the key columns (confirmed in section 4.4) |

**Slot creation rights (guide section 21, resolved):** in Cloud SQL, `postgres` couldn't create the slot at first.
The bootstrap caught the permission error, ran `ALTER ROLE postgres WITH REPLICATION`, and retried. `postgres` now
has `rolreplication = t`.

**Seed (A3, 24 Nov):** 2,160 rows in `g2` (baseline 2,157 plus `S999`, `D999` and the `heartbeat` row),
`store_access` empty. WAL held by the slot: 215 kB after A2, 960 kB after the seed, 1,720 kB just before A4,
61 kB a few minutes after the stream started (Datastream confirms what it has read).

**WAL held by the slot** (must stay small; it grows whenever the stream is paused and the database is running):

```sql
SELECT slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS wal_held
FROM pg_replication_slots;
```

---

## 2. Stream (A4)

Terraform: `terraform/modules/datastream_pg`, called from `terraform/shared/datastream.tf` (commit `2a8f321`,
applied 24 Nov: 6 added, 0 changed, 0 destroyed; the stream took 9 minutes to create and start).

| Item | Value |
| --- | --- |
| Stream | `poc-cdc-stream`, `us-central1`, `RUNNING`, `backfill_all`, append-only (D-25) |
| Source profile | `poc-ops-db-pg`: public IP `136.111.225.230:5432`, database `g2`, user `datastream_user` (password from secret `poc-ops-db-datastream`) |
| SSL | `ssl_config.server_verification` with the Cloud SQL server CA (`cloudsql_g2` output `server_ca_cert`). Accepted: the server certificate check works against the IP |
| Destination profile | `poc-bq`; single target dataset `raw_g2`; tables named `g2_<table>`, clustered on the primary key |
| IAM | Datastream service agent `service-166366601382@gcp-sa-datastream.iam.gserviceaccount.com`: `roles/bigquery.dataEditor` on `raw_g2` only. The agent was created first with `gcloud beta services identity create --service=datastream.googleapis.com` |
| Extra grants | None beyond A2 |
| Backfill | All 11 objects `COMPLETED`; started 07:42:55 UTC, last finished 07:44:09 UTC |

### Rows after the backfill

| Table | Cloud SQL (A3) | `raw_g2` after backfill | `raw_g2_parity` |
| --- | --- | --- | --- |
| `brands` | 4 | 4 | 4 |
| `teams` | 5 | 5 | 5 |
| `statuses` | 7 | 7 | 7 |
| `users` | 18 | 18 | 18 |
| `alert_types` | 11 | 11 | 11 |
| `stores` | 41 | 41 | 41 |
| `device_locations` | 133 | 133 | 133 |
| `alert_incidents` | 450 | 450 | 450 |
| `alert_history` | 1,490 | 1,490 | 1,490 |
| `heartbeat` | 1 | 1 | 1 |
| `store_access` | 0 | no table | no table |
| **Total** | **2,160** | **2,160** | **2,160** |

Every backfilled row has `change_type = 'INSERT'`.

**Seed in the WAL (guide section 21, resolved):** the slot existed before the seed, but the seed was **not** delivered
twice. Each table holds exactly one row per source row.

**`store_access`:** Datastream creates no table for an empty source table. `raw_g2.g2_store_access` appears with the
first insert (`simulator grant`, after 0.7). Staging (A10) and AT-15 (A5) must cope with it missing until then.

---

## 3. `datastream_metadata`

A RECORD column on every `raw_g2` table.

| Field | Type | Example | Meaning |
| --- | --- | --- | --- |
| `uuid` | STRING | `3786a80b-f920-4328-a03c-9adb274a4b1a` | One per change row |
| `source_timestamp` | INTEGER | `1795510091157` | Commit time in **milliseconds** since epoch: `TIMESTAMP_MILLIS(...)`. For backfill rows it is the time the backfill read the row, not when the row was written |
| `change_sequence_number` | STRING | `1a20cbdbd95/0/24eef48` | `<source_timestamp in hex>/<LSN high>/<LSN low>`, lower-case hex, **not zero-padded**. **Does not sort correctly as text** (section 4.5). Backfill rows end in `/0/0` |
| `change_type` | STRING | `INSERT`, `UPDATE`, `DELETE` | Backfill rows are `INSERT` |
| `sort_keys` | REPEATED STRING | `["1795510091157", "0/24EEF48"]` | `[source_timestamp, LSN]`, LSN upper-case hex. Backfill rows have an empty LSN (`""`) |

---

## 4. Shapes

Observed on `g2.heartbeat` with a scratch row `source = 'cdc-test'` (insert 08:48:11, update 08:49:28,
delete 08:49:45 UTC), after the backfill.

### 4.1 Backfill row
`change_type = 'INSERT'`, every column filled, `sort_keys = [<read time ms>, ""]`,
`change_sequence_number = '<hex>/0/0'`.

### 4.2 INSERT
`change_type = 'INSERT'`, every column filled.

### 4.3 UPDATE
**One row**, not an UPDATE-DELETE / UPDATE-INSERT pair. `change_type = 'UPDATE'`, every column holds the **new** value.

### 4.4 DELETE
`change_type = 'DELETE'`. **Only the key columns are filled** (`source`); every other column is `NULL`
(replica identity default).

### 4.5 Ordering
Text comparison of `change_sequence_number` breaks once a hex part gains a digit:
`'1a20cbdbd95/0/ffffff' < '1a20cbdbd95/0/1000000'` is **false** in BigQuery. Order change rows by:

```sql
datastream_metadata.source_timestamp,
CAST(CONCAT('0x', SPLIT(NULLIF(datastream_metadata.sort_keys[SAFE_OFFSET(1)], ''), '/')[SAFE_OFFSET(0)]) AS INT64),  -- LSN high
CAST(CONCAT('0x', SPLIT(NULLIF(datastream_metadata.sort_keys[SAFE_OFFSET(1)], ''), '/')[SAFE_OFFSET(1)]) AS INT64)   -- LSN low
```

A backfill row has no LSN (`NULL` here), so put it first among rows with the same `source_timestamp`
(`ORDER BY ... ASC NULLS FIRST`; reverse for `DESC`).

---

## 5. Replication delay

Method (a throwaway PowerShell loop, not kept in the repo): update `g2.heartbeat` (`source = 'simulator'`) through the proxy, then
poll `raw_g2.g2_heartbeat` every 5–8 s (each poll is a `bq query`, which itself takes a few seconds) until the new
`beat_at` appears. The delay is therefore an upper bound with a resolution of about 5 s.

| Sample | `beat_at` (UTC) | Seen after |
| --- | --- | --- |
| 1 | 09:39:12.578 | ≤ 6 s |
| 2 | 09:39:40.625 | ≤ 7 s |
| 3 | 09:40:09.506 | ≤ 5 s |
| 4 | 09:40:36.669 | ≤ 6 s |
| 5 | 09:41:04.554 | ≤ 6 s |

Every sample appeared at the first poll that could see it: **CDC delay ≤ about 6 s**, well under the minute that the
20-minute budget leaves it (guide 13.2).

---

## 6. Parity snapshot (`raw_g2_parity`)

10 snapshot tables (`CREATE SNAPSHOT TABLE raw_g2_parity.g2_<t> CLONE raw_g2.g2_<t>`), 2,160 rows, all backfill
`INSERT`s; no `store_access` table (nothing to snapshot).

- The first attempt produced **empty** snapshots: the rows were still in the BigQuery write buffer, which queries see
  but `CLONE` doesn't. Fix: check `bq show` (`numRows` > 0, no `streamingBuffer`) before cloning, then compare counts.
- The scratch `cdc-test` rows (section 4) were written before the snapshot, so `g2_heartbeat` was cloned
  `FOR SYSTEM_TIME AS OF '2026-11-24 08:47:00+00'` (just before the test). The other 9 tables were cloned as is.
- Snapshots are read-only. Never drop them: C4 compares against them.

---

## 7. Hand-off notes and corrections

**For A10 (`cdc_current_state()`):**
- `_source_updated_at = TIMESTAMP_MILLIS(datastream_metadata.source_timestamp)`; `_is_delete = change_type = 'DELETE'`.
- Updates are single rows: no pair handling.
- The latest row per key decides: if it is a `DELETE`, the key is deleted (`is_deleted = true`). Because a delete row
  carries only the key, take the non-key columns from the latest non-delete row if a "last known" image is wanted.
- Order with section 4.5, **not** with `change_sequence_number` as text.
- `g2_store_access` doesn't exist yet.

**For C4:** `raw_g2_parity` is frozen (10 tables, 2,160 rows). The dbt var for pointing staging at it
(`g2_raw_dataset`) doesn't exist yet; A10/C4 add it.

**Corrections to the first version of this file (commit `6adbd56`) and `handoff_a4_a5.md`:**
- `change_sequence_number` was said to sort correctly as text. It doesn't (section 4.5).
- The replication-delay table listed two `simulator` updates at 08:52:10 and 08:54:30 UTC. No such rows exist in
  `raw_g2.g2_heartbeat`, and the arrival times of the `cdc-test` samples weren't recorded anywhere. Section 5
  replaces it with measured samples.
- The A2/A3 source set-up section had been removed; restored as section 1.
- The parity snapshot of `g2_heartbeat` now excludes the `cdc-test` rows (section 6).
