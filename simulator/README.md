# simulator

**Owner:** Dev 3  
**Tasks:** 0.6, A7, A8 (code), A9 (writer), B2

`poc-source-simulator`: keeps G2 (Cloud SQL), case events (Pub/Sub), CRM exports and `sim_g2_datalake` changing.
Scripted mode (`seed`, `batch --n 1..3`) for repeatable tests; continuous mode (`tick`) as a Cloud Run job every
5 minutes.

The seed reuses POC 1's generator. Copy `generate_synthetic_data.py` from `data-gen-upload-data-lake-poc` at commit
`4edc2ba` into `simulator/vendor/` and never edit the copy. Phase 2 changes nothing in the Phase 1 repos.

## Files to create here

| File | Task | Owner | Day | Notes |
| --- | --- | --- | --- | --- |
| `Python package, vendor/generate_synthetic_data.py, tests/` | 0.6 | Dev 3 | 1-2 | `seed`, `batch --n 1..3` against PostgreSQL in Docker; needs `sql/g2/schema.sql` (0.5) |
| `expected/batch_1.json` .. `batch_3.json` | 0.6 | Dev 3 | 1-2 | Expected state after each batch (AT-17, AT-18) |
| `Case-event publisher` | A7 | Dev 3 | 4-5 | Planted duplicates |
| `Dockerfile, tick mode, heartbeat, pause switch, RATE` | A8 | Dev 3 (Dev 4: Terraform) | 5-6 | Cloud Run job `poc-source-simulator`, Scheduler `*/5 * * * *` |
| `sim_g2_datalake writer` | A9 | Dev 3 | 5-6 | `wheel_event` by load job, not streaming |
| `CRM export writer` | B2 | Dev 3 | 3-4 | Hourly snapshot, manifest last, `--big-change` |

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".
