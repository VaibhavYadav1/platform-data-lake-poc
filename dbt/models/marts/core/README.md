# dbt/models/marts/core

**Owner:** Dev 1  
**Tasks:** C2, C3, A11

Published dimensions and facts for the alert path. `fct_alert*` start as plain tables (C3, Dev 1); Dev 3 makes them incremental (A11).

## Files to create here

| File | Task | Owner | Day | Notes |
| --- | --- | --- | --- | --- |
| `dim_store` | C2 (+B7 tenant cols) | Dev 1 (Dev 5 for tenant_id) | 3-4 |  |
| `dim_device, dim_alert_type` | C2 | Dev 1 | 3-4 |  |
| `fct_alert, fct_alert_history` | C3 then A11 | Dev 1, then Dev 3 | 4-5, 7-8 | Incremental merge, soft deletes |

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".
