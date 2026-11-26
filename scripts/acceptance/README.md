# scripts/acceptance

**Owner:** Each test's owner  
**Tasks:** AT-15..AT-37

One script per acceptance test: `at<nn>_<name>.py`. Owner is in plan section 12.

## Running the tests

### AT-15: CDC initial copy validation

Validates that the initial CDC copy is complete by comparing row counts between Cloud SQL and BigQuery.

**Prerequisites:**

- Cloud SQL Auth Proxy running on port 5433
- Access to BigQuery dataset (raw_g2 or staging views)

**Usage:**

```powershell
# Test against raw_g2 (before A10 staging views exist)
cloud-sql-proxy gks-datalake-poc2-dev:us-central1:poc-ops-db --port 5433
python scripts/acceptance/at15_cdc_initial.py --raw

# Test against staging views (after A10)
python scripts/acceptance/at15_cdc_initial.py --stg-dataset dbt_<you>_stg
```

**Expected output:** 11/11 tables with matching counts, exit code 0. A missing staging view is reported as `FAIL (view missing)`, not a crash. AT-15 (gate G6) counts only the `--stg-dataset` run; `--raw` is a rehearsal. Evidence file names are UTC.

## Files to create here

| File                          | Task | Owner | Day | Notes              |
| ----------------------------- | ---- | ----- | --- | ------------------ |
| `at15_cdc_initial.py`         | A5   | Dev 2 | 5   | `--raw` rehearsal passes; real run (G6) after A10 |
| `at17_incremental_vs_full.py` | A12  | Dev 3 | 8-9 |                    |
| `run_all.py`                  | -    | Dev 5 | -   | Runs every at\*.py |

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".
