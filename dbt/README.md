# dbt (POC C: transformation layer)

**Owner:** Dev 1 (framework); Dev 4 (Dockerfile, entrypoint.sh)  
**Tasks:** 0.4, C1 to C12, E3

All data comes from **raw sources** (Datastream, Pub/Sub, the CRM loader, the lake). The only CSVs are four small
lookups in `seeds/` (customer types, health rules, golden test scenarios, and the freshness promises in `entity_registry`). No business data is loaded from a file.

## Layers (data flows top to bottom)

| Folder | Dataset | What it holds |
| ------ | ------- | ------------- |
| `models/sources/` | - | `sources.yml`: the raw tables dbt may read, and their freshness limits |
| `models/staging/` | `stg` (views) | `stg_<source>__<table>`: one current, clean row per key. Subfolders `g2`, `crm`, `lpos`, `g2_datalake` |
| `models/intermediate/` | `prep` | Joins and checks: CRM replica, tenant assignment, alert validation (`alert`, `crm`, `tenant`) |
| `models/marts/` | `build` | Published dimensions and facts. Subfolders `core`, `crm`, `lpos`, `wheel`, `calendar` |
| `models/rollups/` | `build` | Health and trend marts (`mv_*`) |
| `models/security/` | `build` | `map_tenant_access` (published to `sec_*`) |
| `seeds/` | `prep` | Lookups: `map_customer_type`, `map_store_health_rule`, `golden_store_health`, `entity_registry` (freshness promises) |
| `macros/` | - | Shared logic (below) |
| `tests/` | `dq` | Singular tests: DQ rules, AT-19 checks, golden scenarios |

## Rules

- One `.sql` and one `.yml` per model, named after the model (no shared `schema.yml`: that is where merge conflicts come from).
- Naming: `stg_<source>__<table>`, `int_<entity>__<verb>`, `dim_<entity>`, `fct_<process>`, `mv_<rollup>`.
- Marts, rollups and security models have enforced contracts: every column has a `data_type` and a description, and
  every model has key tests. `scripts/ci/check_dbt_conventions.py` enforces this.
- The customer definition lives only in `macros/is_customer.sql` and `seeds/map_customer_type.csv`
  (`scripts/ci/check_single_definition.py` enforces it).

## Macros

| Macro | Purpose |
| ----- | ------- |
| `generate_schema_name` | One dataset per layer (`build_dev`, or `dbt_<you>_build` on a laptop) |
| `cdc_current_state` | Change log to one current row per key, deletes flagged |
| `is_customer`, `is_open_alert` | The single definitions |
| `tokenize` | Keyed hash of personal data |
| `lineage_columns`, `hierarchy_columns`, `snapshot_ts` | Shared column groups and the run's as-of time |
| `incremental_filter` | Lookback window and older-change guard for incremental facts |
| `freshness_check` | `dbt run-operation freshness_check`: measures each entity against its promise in `entity_registry` (E7) |
| `log_dq_results` | `on-run-end` hook: appends every test result to `ops_<env>.dq_result` |

## Run it locally

```
set -a; . ./.env; set +a          # bash. PowerShell: see the bottom of .env
dbt deps
dbt compile --target local         # renders every model, no data needed
dbt seed --target local
dbt build --target local           # needs the raw tables and keys.token_key
```

Local builds go to `dbt_<DBT_USER>_*`, never to `build_dev` or `wh_dev`.

See `GKS-POC-Phase2-detailed-plan.md` (section 8) for each task's "done when".
