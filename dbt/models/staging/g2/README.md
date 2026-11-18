# dbt/models/staging/g2

**Owner:** Dev 3  
**Tasks:** A10

Views over the Datastream change log: current state per key, deletes flagged.

## Files to create here

| File | Task | Owner | Day | Notes |
| --- | --- | --- | --- | --- |
| `stg_g2__<table>.sql/.yml (one per G2 table)` | A10 | Dev 3 | 3-4 | Use `cdc_current_state()` |

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".
