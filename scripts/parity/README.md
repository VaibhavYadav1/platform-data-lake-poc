# Parity scripts (task C4, AT-26a)

Each `.sql` file compares one POC 1 table with its dbt counterpart, both ways. **Expected result: zero rows.**
Explain any other result, row by row, in `docs/poc2/parity.md`.

Placeholders: `{project}` (the GCP project), `{user}` (your `DBT_USER`). Column names follow the rename rules on the
schema page (`fk_store` -> `store_id`, `alert_type` -> `alert_type_id`, ...). Check them against `poc1_baseline`.

1. Build from the frozen copy:
   ```
   dbt build --target local --vars '{g2_raw_dataset: raw_g2_parity}' --select +fct_alert +fct_alert_history +dim_store +dim_device +dim_alert_type
   ```
2. Run each file, for example:
   ```
   sed 's/{project}/gks-datalake-poc2-dev/; s/{user}/<you>/' fct_alert.sql | bq query --use_legacy_sql=false
   ```
3. `assignee_users.sql` checks the user count. `tenant_id` and the lineage columns are new and are not compared.

Re-run after A11 made the facts incremental.
