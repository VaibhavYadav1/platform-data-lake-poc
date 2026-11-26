# apps/tenant_reader

**Owner:** Dev 2  
**Tasks:** D7

Test application (command line) that impersonates `sa-app-tenant-a` / `sa-app-tenant-b`.

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".

## How it works

1. Runs as whoever calls it: `sa-test-app` in the test. That account has token creator on `sa-app-tenant-a` and
   `sa-app-tenant-b` only, and nothing in BigQuery.
2. Looks up the tenant's service account in `config.yaml`, impersonates it, and runs one named query from the
   catalog in `reader.py` (`store_health`, `tenant_summary`, `alerts`) against `wh_<env>`, with
   `maximum_bytes_billed`.
3. Command-line values are always query parameters, never SQL text. Prints one JSON line per row, then a `DONE`
   line with `tenants_seen` and the job id.

## Run it

From `apps/`, with `pip install -r tenant_reader/requirements.txt`, logged in as (or impersonating) `sa-test-app`:

```bash
python -m tenant_reader --tenant A --query store_health
python -m tenant_reader --tenant B --query tenant_summary
python -m tenant_reader --tenant A --query alerts --date-from 2026-11-01 --date-to 2026-11-30
python -m tenant_reader --tenant A --query store_health --filter-tenant ACC00005   # tenant B's id
python -m tenant_reader --impersonate-writer
```

## AT-24 application part: the checks

| Check | Command | Pass |
| --- | --- | --- |
| A and B see different rows | `--tenant A` and `--tenant B`, `--query tenant_summary` | A shows only `ACC00001`, B only `ACC00005` |
| A filtered on B's id | `--tenant A --filter-tenant ACC00005` | `DONE` with `rows: 0` |
| No route to the writer | `--impersonate-writer` | `outcome: refused`, exit 0 (exit 1 means the caller can act as the writer) |

Needs D2 (identities), D3 (`store_access` rows: `python -m simulator store-access-seed`) and D4 (row policies on
`wh_<env>`).

## Tests

`python -m pytest apps/tenant_reader/tests` (no Google Cloud; fakes stand in for impersonation and BigQuery).
