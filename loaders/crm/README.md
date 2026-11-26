# loaders/crm

**Owner:** Dev 3  
**Tasks:** B3, B5

`poc-crm-loader` is a Cloud Run job. It loads complete CRM export folders from GCS into `raw_crm`, once each, and holds
an export that changes too many accounts (DQ42).

| File | What it is |
| --- | --- |
| `crm_loader.py` | The loader. All settings are command-line arguments; it reads no environment variables |
| `create_raw_crm.py` | Creates the `raw_crm` dataset, the three landing tables and `load_log` |
| `make_test_exports.py` | Writes test export folders (including a big-change one) |
| `Dockerfile`, `requirements.txt` | The image. Cloud Build builds it on every merge to main, tagged with the commit SHA |
| `tests/` | `python -m pytest loaders/crm/tests` (no network: GCS and BigQuery are faked) |

## The automatic flow

```
poc-simulator-tick (every 5 min)  ->  poc-source-simulator  ->  gs://<project>-crm-exports/crm/export_ts=<ts>/
                                                                 account.csv store.csv work_order.csv  manifest.json (last)
poc-micro-batch-<env> (every 15 min):  load_crm (this job)  ->  dbt build  ->  publish
```

- **An hour is never skipped by a late tick.** Every simulator tick writes any of the last 4 hourly exports that has no
  `manifest.json` yet, oldest first. A complete export is never rewritten.
- **Only complete exports are read.** A folder without `manifest.json` does not exist as far as the loader is concerned.
  With a manifest, the loader still checks that all three files are listed, no other file is there, and every size and MD5 matches.
- **Exactly once.** `raw_crm.load_log` has one row per attempt; the newest row of an `export_ts` decides:
  `LOADED` is skipped, `HELD` waits for a person, `FAILED` (or no row) is loaded again after removing any rows that export left behind.
  After loading, the loader counts the rows per table; if another loader ran at the same time the count is wrong and the run fails and cleans up.

## Arguments

```
python crm_loader.py --bucket <bucket> [--prefix crm] [--project <project>] [--dataset raw_crm] [--location us-central1]
python crm_loader.py --bucket <bucket> --approve export_ts=<YYYYMMDDTHHMMSSZ>
```

The Cloud Run job (`terraform/shared/crm_exports.tf`) and the workflow (`orchestration/micro_batch.workflow.yaml`, step
`load_crm`) both pass `--bucket`, `--prefix` and `--project`.

## When something is not normal

| Log line / status | What it means | What the pipeline does | What you do |
| --- | --- | --- | --- |
| `HELD`, `crm_guard_tripped` (alert email) | More than 50% of the accounts changed since the last loaded export. Nothing was loaded | Exit 0. Later exports wait behind it. dbt runs on the data loaded last | Look at the export. If it is right: run the job once with `--approve export_ts=<ts>`; the next micro-batch loads it. The guard is never approved automatically |
| `FAILED` | Bad manifest, checksum, header, row count, or the load itself failed. Partial rows are removed | Exit 1. The workflow fails, dbt does not run, the failed-workflow alert fires. The next run tries again | Read `error_message` in `raw_crm.load_log`; fix the cause. No manual retry is needed |
| No new `LOADED` rows for hours | The simulator is not writing (job, scheduler, or `CRM_BUCKET`) | The `freshness` check on `raw_crm` reports it | Check `poc-simulator-tick` and the simulator job's logs |

Do not run the loader by hand while a micro-batch is running. The row count check catches an overlap, but it fails the run.

## Release a HELD export

```
gcloud run jobs execute poc-crm-loader --region us-central1 --wait \
  --args="--bucket=<bucket>,--prefix=crm,--project=<project>,--approve=export_ts=<ts>"
```
