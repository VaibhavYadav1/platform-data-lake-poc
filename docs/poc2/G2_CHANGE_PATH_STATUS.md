# G2 change path: implementation status

**Reference:** POC A guide (`docs/GKS-POC-Phase2-POC-A-real-time-path.html`), section 4.4 A "G2 change path"
and D "Heartbeat path"; task table 15.1.  
**Checked:** 24 Nov 2026, against GCP (Cloud SQL, Datastream, BigQuery) and `main` at `070540c`, not only the build log.

## The path

```
simulator tick (A8)
  → g2.<table> in Cloud SQL poc-ops-db (A1, A2, seeded in A3)
  → WAL · poc_pub · poc_slot (A2)
  → poc-cdc-stream, Datastream, append-only (A4)
  → raw_g2.g2_<table> (A4)                       ← AT-15 proves the first copy (A5)
  → stg_g2__<table>, cdc_current_state() (A10)
  → int_alert__validated (C7, POC C)
  → build.fct_alert / fct_alert_history, incremental merge (A11; AT-17 via A12, AT-18)
  → wh.fct_alert, publish.py (E5, POC E)
  → mv_store_health (C5, POC C)                  ← AT-16: a change reaches store health in time
```

Heartbeat path (D): tick's last step updates `g2.heartbeat` → `poc-cdc-stream` → `raw_g2.g2_heartbeat` →
`poc-watchdog` (E7) every 5 minutes → alert email if older than 8 minutes.

## Short answer

**No, the G2 change path is not complete.** The source and CDC half is built and proven (A1–A4). Everything from
staging onward is open: A5 is written and rehearsed but its real run waits for A10, A10 is half-built and not in the
repo, and A8, A11 and A12 haven't started.

## Status by step

| Step | Task | Status | Evidence (24 Nov) |
| --- | --- | --- | --- |
| Source database | A1 | ✅ Done | `poc-ops-db` RUNNABLE, `wal_level = logical`, SSL only (23 Nov) |
| Publication, slot, users | A2 | ✅ Done | `poc_pub` (11 tables), `poc_slot` now `active = t` |
| Seed + probe rows | A3 | ✅ Done | 2,160 rows = baseline 2,157 + `S999`, `D999`, heartbeat |
| Datastream into `raw_g2` | A4 | ✅ Done | Stream RUNNING; backfill 2,160 rows, no duplicates; `raw_g2_parity` 10 tables / 2,160 rows; `cdc.md` |
| Announce "parity snapshot taken" | A4 | ⚠️ Not done | Lifts the A3 freeze for Dev 1 (C4) and Dev 3 (simulator). A person must send it |
| First-copy proof (AT-15) | A5 | 🟡 Script done, test not passed | `--raw` rehearsal passes 11/11 (`docs/poc2/evidence/at15_20261124T145732Z.json`). Against `dbt_dev_stg`: 9/11, two views missing. Done when = AT-15 passes **against the staging views** (gate G6); blocked by A10 |
| Change-data staging | A10 | 🟡 Started, not in repo | 9 views in `dbt_dev_stg` (deployed 10:35 UTC); `dbt/models/staging/g2/` holds only a README. Missing `stg_g2__heartbeat` and `stg_g2__store_access`. Orders by `change_sequence_number` as text (wrong, `cdc.md` 4.5). The 9 views' non-deleted counts equal Cloud SQL |
| Continuous changes (tick) | A8 | ⏳ Not started | No `tick` command, no `poc-source-simulator` job, no `poc-simulator-tick` scheduler, no `sa-simulator`. Needs A7 → A6 |
| Validated alerts | C7 | ⏳ POC C | |
| Incremental facts | A11 | ⏳ Not started | Needs C3 and A10. Done when AT-18 passes |
| Scripted-batch harness | A12 | ⏳ Not started | Needs A11. Done when AT-17 passes |
| Publish to `wh_dev` | E5 | ⏳ POC E | |
| Store health | C5 | ⏳ POC C | AT-16 (end-to-end latency) needs C5 and E5 |
| Watchdog on the heartbeat | E7 | 🟡 Built, paused | `poc-watchdog` scheduler exists (PAUSED); `alert_email` empty, so nobody is notified (section 21, Dev 4) |
| Private connectivity | A13 | Stretch | Only after gate G7 |

## Pending, in order

**Step-by-step for the critical path (A4 close → A10 → A5 → G6): `docs/poc2/CRITICAL_PATH_G6.md`.** A10's code is on branch `origin/poc_c_dbt` (with POC C), not on `main`; that document brings it over and fixes the ordering and the missing `g2_store_access` table (rehearsed 24 Nov: 38/38, AT-15 11/11).

1. **Announce the parity snapshot** (A4): one message to Dev 1 and Dev 3.
2. ~~**Fix the A5 script**~~ ✅ Done 24 Nov: `store_access` key is `principal, crm_account_id`; evidence names are
   UTC; a missing staging view is reported as `FAIL (view missing)` instead of crashing; README wording fixed;
   evidence reduced to the `--raw` pass (`at15_20261124T145732Z.json`), the negative test and a pre-A10 staging run
   (`..._stg_pre_a10.json`: 9/11 OK, `store_access` and `heartbeat` views missing).
3. **Finish A10** (Dev 3): commit `cdc_current_state()` and all 11 views to `dbt/models/staging/g2/`; add
   `stg_g2__heartbeat` and `stg_g2__store_access` (the raw table doesn't exist yet: the source must tolerate that);
   order by `source_timestamp`, then the LSN from `sort_keys[1]` parsed from hex (`cdc.md` 4.5), not `_seq`.
4. **Run AT-15 for real** (Dev 2): `at15_cdc_initial.py --stg-dataset dbt_dev_stg` → 11/11 → gate G6. Record the
   result (`ops_dev` exists now; the `acceptance_result` table doesn't yet).
5. **A6 → A7 → A8** (Dev 4, Dev 3): case-event infrastructure, publisher, then the simulator in the cloud. A8 is
   what makes the path change continuously; until then only hand-made changes and scripted batches reach `raw_g2`.
6. **A11 → A12** (Dev 3, after C3): incremental facts, AT-18, then the batch harness, AT-17.
7. **POC C/E pieces** (C7, C5, E5) close the path to `mv_store_health`; then AT-16, then gate G7.

## Rules that still hold

- Never re-seed Cloud SQL or `--reset` it now that the stream exists (old rows would arrive in `raw_g2` as deletes).
- Never drop `raw_g2_parity`.
- Evening: pause the stream, then stop the database. Morning: the reverse. A paused stream with a running database
  lets the slot's WAL grow (guide 7.5: at most an hour).
