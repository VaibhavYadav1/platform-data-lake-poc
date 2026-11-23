# Baseline

**Owner:** Dev 1  
**Tasks:** 0.3  
**Frozen:** 17 Nov 2026 (snapshots); recorded 20 Nov 2026

The frozen POC 1 state that POC 2 starts from. Task A3 seeds Cloud SQL `g2` from the same batch, and the parity
test (C4, AT-26a) compares POC 2 with the snapshots below. Don't change either.

## Batch

| Item | Value |
| --- | --- |
| Batch folder | `clean_data_20261116_190645` |
| Location | `gs://data-lake-raw-512405/clean_data_20261116_190645/` (Phase 1 project `data-lake-poc-512405`, bucket in `asia-south1`) |
| Contents | 9 CSVs + `manifest.json` |
| Kind | `clean` (no planted errors) |
| Loaded into `poc_dwh_dev` | 16 Nov 2026, 19:08–19:09 UTC, by the POC 1 ETL job (`etl-pipeline-job-service`) |
| ETL result | 9 runs, all `SUCCEEDED`; 2157 source rows, 2157 accepted, 2157 loaded, 0 rejected |

## Row count per table

Accepted rows equal file rows (0 rejected), so these are also the counts A3 must see in Cloud SQL, before the
probe rows are added.

| Batch file / G2 table | POC 1 warehouse table | Accepted rows |
| --- | --- | ---: |
| `brands` | `dim_brand` | 4 |
| `teams` | `dim_team` | 5 |
| `statuses` | `dim_status` | 7 |
| `users` | `dim_user` | 18 |
| `alert_types` | `dim_alert_type` | 11 |
| `stores` | `dim_store` | 40 |
| `device_locations` | `dim_device` | 132 |
| `alert_incidents` | `fct_alert_incident` | 450 |
| `alert_history` | `fct_alert_history` | 1490 |
| **Total** | | **2157** |

`store_access` and `heartbeat` are new in POC 2 and have no baseline count.

## Snapshots in `data-lake-poc-512405.poc1_baseline` (`us-central1`)

All are BigQuery snapshot tables: read-only, point-in-time copies.

| Snapshots | Copied from | Snapshot time (UTC) | Purpose |
| --- | --- | --- | --- |
| `bak_dim_*`, `bak_fct_*` (9) | `poc_dwh_dev` | 17 Nov 2026 09:31 | Backup before the freeze (plan 0.3 step 2) |
| `dim_*`, `fct_*` (9) | `poc_dwh_dev` | 17 Nov 2026 10:32 | **The baseline**: what parity compares against |
| `map_store_health_rule`, `mv_*` (7) | `poc_analytics_dev` | 17 Nov 2026 12:27 | POC 1 marts, for mart-level parity |

## Deviation from the plan: no reload

Plan 0.3 step 3 says to empty the 9 `poc_dwh_dev` tables and load one clean batch. That was skipped: the tables
already held exactly one clean batch. Every row's `_run_id` maps, through `poc_ops_dev.etl_run_log`, to
`clean_data_20261116_190645`, with one run per table and nothing loaded after it (last modified 16 Nov 19:09 UTC,
before both snapshot sets). A reload would have rebuilt the same state.

Check it again with:

```sql
SELECT l.source_folder, COUNT(*) AS rows_, COUNT(DISTINCT f._run_id) AS runs
FROM `data-lake-poc-512405.poc1_baseline.fct_alert_incident` f
LEFT JOIN `data-lake-poc-512405.poc_ops_dev.etl_run_log` l ON l.run_id = f._run_id
GROUP BY 1;
-- expect: clean_data_20261116_190645 | 450 | 1
```

## Rules

- Don't delete or overwrite the batch folder. The bucket has no lifecycle deletion (soft delete keeps deleted
  objects for 7 days only).
- Don't change the `poc1_baseline` snapshots. If `poc_dwh_dev` is reloaded later, the baseline is still the
  snapshots, not the live tables.
