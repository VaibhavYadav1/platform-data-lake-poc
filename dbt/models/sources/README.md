# dbt/models/sources

**Owner:** Each source's owner; freshness values Dev 4  
**Tasks:** C12

One `sources_<system>.yml` per source system, so owners don't edit the same file.

## Files to create here

| File | Task | Owner | Day | Notes |
| --- | --- | --- | --- | --- |
| `sources_g2.yml` | A10 | Dev 3 | 3-4 | `raw_g2`, `raw_g2_parity` via var |
| `sources_crm.yml` | B4 | Dev 3 | 5-6 | `raw_crm` |
| `sources_lpos.yml` | C10 | Dev 4 | 7-8 | `raw_lpos` |
| `sources_g2_datalake.yml` | A9 | Dev 1 | 5-6 | `sim_g2_datalake` |
| freshness blocks in each file | C12 | Dev 4 | 7 | Values from `entity_registry` |

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".
