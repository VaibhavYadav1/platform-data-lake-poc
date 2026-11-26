# POC A: implementation status

**Reference:** POC A guide, task table 15.1 and gates (AT-15 → G6; AT-16, AT-17, AT-18 → G7).  
**Checked:** 24 Nov 2026 against GCP and `main` at `070540c`. The G2 path in detail: `G2_CHANGE_PATH_STATUS.md`.

## Summary

**4 of 12 tasks done (A1–A4)**, plus A13 as a stretch. A5 and A10 are part-way. Nothing on the case-event,
wheel-event or continuous-simulator side exists in GCP yet.

| Task | What | Owner | Needs | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| A1 | Cloud SQL `poc-ops-db` | Dev 2 | 0.10 | ✅ Done 23 Nov | |
| A2 | Replication bootstrap | Dev 2 | A1, 0.5 | ✅ Done 23 Nov | |
| A3 | Seed + probe store | Dev 3 | A2, 0.3, 0.6 | ✅ Done 24 Nov | `store_access` empty until 0.7 |
| A4 | Datastream, backfill, parity snapshot, `cdc.md` | Dev 2 | A2, A3 | ✅ Done 24 Nov | Announcement to Dev 1/Dev 3 still to send |
| A5 | AT-15 script | Dev 2 | A4, A10 | 🟡 Script written, `--raw` rehearsal 11/11 | Review fixes done 24 Nov; against `dbt_dev_stg` 9/11 (two views missing); real run needs A10 |
| A6 | Case events: Avro schema, topic, `raw_lpos.case_event`, BigQuery subscription, dead letters | Dev 4 | 0.7 | ⏳ Not started | `specs.md` (0.7) is still "To be written"; build from the guide's proposed schema (11.2) and confirm it with Dev 5. Steps: `A6_STEPS.md` |
| A7 | Case-event publisher with planted duplicates | Dev 3 | A6 | ⏳ Not started | |
| A8 | Simulator in the cloud (image, Cloud Run job, Scheduler every 5 min, heartbeat, pause switch, rate) | Dev 3, Dev 4 | A3, A4 snapshot, A7 | 🟡 Deployed 25 Nov (schedule paused) | `tick`, Dockerfile, `terraform/shared/simulator.tf`; 8 tick tests pass. Deploy and checks: `A8_STEPS.md`. Case events wait for A6/A7 |
| A9 | `sim_g2_datalake` + `derived_alert` scheduled query + writer | Dev 1, Dev 3 | A8 | ⏳ Not started | |
| A10 | `cdc_current_state()` + 11 `stg_g2__*` views | Dev 3 | A4 | 🟡 Started, not in repo | 9 views in `dbt_dev_stg`; heartbeat and store_access missing; text ordering on `_seq` must change |
| A11 | Incremental `fct_alert`, `fct_alert_history` | Dev 3 | C3, A10 | ⏳ Not started | Done when AT-18 passes |
| A12 | Scripted-batch harness | Dev 3 | A11 | ⏳ Not started | Done when AT-17 passes |
| A13 | Datastream private connectivity | Dev 2 | G7 | Stretch | |

## What the continuous simulator (A8) must do, per guide section 10.5

One tick at `RATE=1.0` (the rate scales these numbers; it isn't a count):

| Source | Per tick |
| --- | --- |
| G2 incidents | Open 3–6, update 3–6, close 2–5, a history row for each. Delete one about every 10 ticks; move a device about every 50 |
| Case events | Publish 1–5, never 0; about 2% duplicate `event_id`s, about 1% unknown store |
| Wheel events | Append 50–200 rows to `sim_g2_datalake.wheel_event` with a load job; about 0.5% unknown wheel (DQ43) |
| CRM | First tick after each full hour: one export (B2) |
| Planted defects | About 0.5% of new incidents: unknown device (DQ33) or future time (DQ34) |
| Heartbeat | Last step: `UPDATE g2.heartbeat SET beat_at = now() WHERE source = 'simulator'` |

Configuration (`PG_INSTANCE`, `PG_SECRET`, rate, pause switch) and the Cloud Run/Scheduler Terraform are in guide
section 10 and its runbook phase. Done when it runs every 5 minutes for 2 hours with no failures, and every source changes.

## What `sim_g2_datalake` (A9) holds, per guide section 12

| Table | Written by | Columns |
| --- | --- | --- |
| `wheel` | Simulator seed (load job) | `wheel_id`, `g2_store_id`, `cart_id`, `installed_at`, `status`; about 20 per active store |
| `wheel_event` | Every tick (load job, append) | `event_id`, `wheel_id`, `event_type` (LOCK, UNLOCK, EXIT_ATTEMPT, LOW_BATTERY), `event_ts`; partitioned on `DATE(event_ts)` |
| `derived_alert` | Hourly scheduled query only | One row per wheel per hour with 3+ EXIT_ATTEMPTs (columns proposed, guide 12.3) |

## Next, in order

1. Send "parity snapshot taken" (A4).
2. Dev 3 finishes and commits A10; run AT-15 against `dbt_dev_stg` → **G6**.
3. In parallel: A6 (Dev 4) with Dev 5 confirming the Avro schema; then A7 → A8 → A9.
4. After C3: A11 → A12; with C5, C7 and E5: AT-16 → **G7**.

## What exists in GCP today (24 Nov)

- Cloud SQL `poc-ops-db`, slot `poc_slot` (active), Datastream `poc-cdc-stream` (RUNNING).
- BigQuery: `raw_g2` (10 tables), `raw_g2_parity` (10 snapshots), `dbt_dev_*` datasets (9 `stg_g2__*` views in
  `dbt_dev_stg`), `ops_dev`, `raw_crm`, `keys`.
- Schedulers, all PAUSED: `poc-night-off`, `poc-morning-on`, `poc-watchdog`, `poc-micro-batch-dev`, `poc-full-load-dev`.
- Not yet: any Pub/Sub topic, `raw_lpos`, `sim_g2_datalake`, `sa-simulator`, `poc-source-simulator`, `poc-simulator-tick`.
