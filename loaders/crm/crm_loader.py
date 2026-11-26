"""poc-crm-loader: load complete CRM export folders from GCS into BigQuery raw_crm (POC B, tasks B3 and B5).

Bucket layout:   <prefix>/export_ts=<YYYYMMDDTHHMMSSZ>/{account.csv, store.csv, work_order.csv, manifest.json}
manifest.json:   {"export_ts": "...", "files": [{"name": "account.csv", "size": 123, "md5": "<hex>"}, ...]}   (written last)

One run:
  1. List the folders that have a manifest.json, oldest first.
  2. Skip folders whose newest load_log row is LOADED.
  3. Stop at the first HELD folder that has not been approved.
  4. Validate the folder: every file listed, present, size and MD5 match.
  5. Change-size guard (DQ42): more than 50% of accounts changed since the last loaded export -> HELD, stop.
  6. Load the three CSVs with WRITE_APPEND, the explicit schema and skip_leading_rows=1.
  7. On any failure delete that export_ts's rows from the landing tables, log FAILED, stop (the next run retries).
  8. Write a load_log row for every outcome.

Approval:  python crm_loader.py --approve export_ts=<YYYYMMDDTHHMMSSZ>   releases a HELD folder; the next run loads it.
Exit code: 0 normal (including HELD), 1 if a folder FAILED.
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from google.cloud import bigquery, storage

from create_raw_crm import DEFAULT_DATASET, DEFAULT_LOCATION, DEFAULT_PROJECT, TABLES, schema_fields

LOADED, HELD, FAILED = "LOADED", "HELD", "FAILED"
THRESHOLD = 0.5  # approved: more than 50% changed -> HELD
FILE_TABLE = {"account.csv": "account_landing", "store.csv": "store_landing", "work_order.csv": "work_order_landing"}
FOLDER_PREFIX = "export_ts="
TS_FORMAT = "%Y%m%dT%H%M%SZ"


class LoaderError(Exception):
    pass


@dataclass
class State:
    status: str
    approved: bool


# ---------------------------------------------------------------- pure functions (unit tested) -------------

def parse_ts(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def folder_ts(folder_name: str) -> datetime:
    """'export_ts=20261120T080000Z' -> datetime."""
    return datetime.strptime(folder_name[len(FOLDER_PREFIX):], TS_FORMAT).replace(tzinfo=timezone.utc)


def manifest_ts(value: str) -> datetime | None:
    """The manifest's export_ts, in the folder format (20261120T080000Z) or ISO."""
    try:
        return datetime.strptime(value, TS_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return parse_ts(value)
        except ValueError:
            return None


def md5_hex(b64: str) -> str:
    """GCS reports md5 as base64; the manifest uses hex."""
    return base64.b64decode(b64).hex()


def change_ratio(previous: set[tuple[str, datetime | None]], current: set[tuple[str, datetime | None]]) -> float | None:
    """Changed rows / rows in the previous export. None when there is no previous export.

    Changed rows: (account_id, updated_at) pairs that are new, plus accounts that disappeared from the previous export.
    """
    if not previous:
        return None
    new_pairs = current - previous
    previous_ids = {a for a, _ in previous}
    current_ids = {a for a, _ in current}
    disappeared = previous_ids - current_ids
    return (len(new_pairs) + len(disappeared)) / len(previous)


def guard_trips(ratio: float | None, threshold: float = THRESHOLD) -> bool:
    return ratio is not None and ratio > threshold


def read_account_pairs(csv_bytes: bytes) -> set[tuple[str, datetime | None]]:
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    return {(r["account_id"], parse_ts(r["updated_at"])) for r in reader}


# ---------------------------------------------------------------- GCS --------------------------------------

def discover(gcs: storage.Client, bucket: str, prefix: str) -> dict[datetime, dict[str, storage.Blob]]:
    """Folders that have a manifest.json, as {export_ts: {file name: blob}}, oldest first."""
    folders: dict[str, dict[str, storage.Blob]] = {}
    for blob in gcs.list_blobs(bucket, prefix=f"{prefix}/{FOLDER_PREFIX}"):
        parts = blob.name[len(prefix) + 1:].split("/", 1)
        if len(parts) == 2 and parts[1]:
            folders.setdefault(parts[0], {})[parts[1]] = blob
    found = {folder_ts(name): files for name, files in folders.items() if "manifest.json" in files}
    return dict(sorted(found.items()))


def check_csv(name: str, data: bytes, ts: datetime) -> int:
    """Structure of one export file: header equals the landing table's columns, every row carries the folder's
    export_ts and has one value per column. Returns the number of data rows (what the load job should load)."""
    expected = [c.name for c in TABLES[FILE_TABLE[name]].columns]
    rows = list(csv.reader(io.StringIO(data.decode("utf-8"))))
    if not rows or rows[0] != expected:
        raise LoaderError(f"{name}: header {rows[0] if rows else '(empty file)'} is not {expected}")
    ts_col = expected.index("export_ts")
    for line, row in enumerate(rows[1:], start=2):
        if len(row) != len(expected):
            raise LoaderError(f"{name} line {line}: {len(row)} values, expected {len(expected)}")
        try:
            row_ts = parse_ts(row[ts_col])
        except ValueError:
            row_ts = None
        if row_ts != ts:
            raise LoaderError(f"{name} line {line}: export_ts {row[ts_col]!r} is not the folder's {ts.strftime(TS_FORMAT)}")
    return len(rows) - 1


def validate(files: dict[str, storage.Blob], ts: datetime) -> dict[str, bytes]:
    """Manifest checks, then file checks. Returns the file contents so the guard need not download them again.

    Manifest: it names this export_ts, lists the three files, and every listed file is present with the stated size
    and MD5. Files: nothing unlisted sits in the folder, and each CSV passes check_csv."""
    manifest = json.loads(files["manifest.json"].download_as_bytes())
    if "export_ts" in manifest and manifest_ts(manifest["export_ts"]) != ts:
        raise LoaderError(f"manifest is for export_ts {manifest['export_ts']}, the folder is {ts.strftime(TS_FORMAT)}")
    listed = {f["name"]: f for f in manifest.get("files", [])}
    missing = set(FILE_TABLE) - set(listed)
    if missing:
        raise LoaderError(f"manifest does not list {sorted(missing)}")
    unlisted = set(files) - set(listed) - {"manifest.json"}
    if unlisted:
        raise LoaderError(f"files in the folder that the manifest does not list: {sorted(unlisted)}")
    for name, entry in listed.items():
        blob = files.get(name)
        if blob is None:
            raise LoaderError(f"{name} is listed in the manifest but not in the folder")
        if blob.size != entry["size"]:
            raise LoaderError(f"{name}: size {blob.size} does not match manifest {entry['size']}")
        if md5_hex(blob.md5_hash) != entry["md5"].lower():
            raise LoaderError(f"{name}: MD5 does not match manifest")
    return {name: files[name].download_as_bytes() for name in FILE_TABLE}


# ---------------------------------------------------------------- BigQuery ---------------------------------

class Warehouse:
    def __init__(self, project: str, dataset: str, location: str):
        self.bq = bigquery.Client(project=project, location=location)
        self.ds = f"{project}.{dataset}"

    def states(self) -> dict[datetime, State]:
        sql = (f"SELECT export_ts, status, approved FROM `{self.ds}.load_log` "
               "QUALIFY ROW_NUMBER() OVER (PARTITION BY export_ts ORDER BY logged_at DESC) = 1")
        return {r.export_ts: State(r.status, r.approved) for r in self.bq.query(sql).result()}

    def last_loaded_accounts(self, states: dict[datetime, State]) -> set[tuple[str, datetime | None]]:
        loaded = [ts for ts, s in states.items() if s.status == LOADED]
        if not loaded:
            return set()
        job = self.bq.query(
            f"SELECT account_id, updated_at FROM `{self.ds}.account_landing` WHERE export_ts = @ts",
            job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("ts", "TIMESTAMP", max(loaded))]))
        return {(r.account_id, r.updated_at) for r in job.result()}

    def load_csv(self, uri: str, table: str) -> int:
        cfg = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV, skip_leading_rows=1,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            schema=schema_fields(TABLES[table], None), max_bad_records=0)
        job = self.bq.load_table_from_uri(uri, f"{self.ds}.{table}", job_config=cfg)
        job.result()
        return job.output_rows

    def count_export(self, ts: datetime) -> dict[str, int]:
        """Rows now in each landing table for this export_ts, by file name."""
        counts = {}
        for fname, table in FILE_TABLE.items():
            job = self.bq.query(
                f"SELECT COUNT(*) AS n FROM `{self.ds}.{table}` WHERE export_ts = @ts",
                job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("ts", "TIMESTAMP", ts)]))
            counts[fname] = next(iter(job.result())).n
        return counts

    def delete_export(self, ts: datetime) -> None:
        for table in FILE_TABLE.values():
            self.bq.query(
                f"DELETE FROM `{self.ds}.{table}` WHERE export_ts = @ts",
                job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("ts", "TIMESTAMP", ts)])).result()

    def log(self, ts: datetime, folder: str, status: str, *, file_count=None, rows=None, ratio=None,
            approved=False, error=None) -> None:
        rows = rows or {}
        row = {
            "export_ts": ts.isoformat(), "folder": folder, "status": status, "file_count": file_count,
            "account_rows": rows.get("account.csv"), "store_rows": rows.get("store.csv"),
            "work_order_rows": rows.get("work_order.csv"), "change_ratio": ratio, "approved": approved,
            "error_message": error, "loader_execution": os.environ.get("CLOUD_RUN_EXECUTION"),
            "logged_at": datetime.now(timezone.utc).isoformat(),
        }
        errors = self.bq.insert_rows_json(f"{self.ds}.load_log", [row])
        if errors:
            raise RuntimeError(f"could not write load_log: {errors}")


# ---------------------------------------------------------------- run --------------------------------------

def run(bucket: str, prefix: str, project: str, dataset: str, location: str, approve: str | None) -> int:
    gcs = storage.Client(project=project)
    wh = Warehouse(project, dataset, location)

    if approve:
        ts = folder_ts(FOLDER_PREFIX + approve.split("=", 1)[-1])
        state = wh.states().get(ts)
        if state is None or state.status != HELD:
            print(f"cannot approve {approve}: its latest status is {state.status if state else 'not logged'}, not HELD")
            return 1
        wh.log(ts, f"gs://{bucket}/{prefix}/{FOLDER_PREFIX}{ts.strftime(TS_FORMAT)}/", HELD, approved=True,
               error="approved by a person; will load on the next run")
        print(f"approved {ts.strftime(TS_FORMAT)}; run the loader again to load it")
        return 0

    states = wh.states()
    failed = False
    for ts, files in discover(gcs, bucket, prefix).items():
        name = ts.strftime(TS_FORMAT)
        folder = f"gs://{bucket}/{prefix}/{FOLDER_PREFIX}{name}/"
        state = states.get(ts)
        if state and state.status == LOADED:
            print(f"{name}: already loaded, skipped")
            continue
        if state and state.status == HELD and not state.approved:
            print(f"{name}: HELD and not approved; later exports wait behind it")
            break
        approved = bool(state and state.status == HELD and state.approved)
        ratio = None
        rows: dict[str, int] = {}
        try:
            contents = validate(files, ts)
            expected_rows = {n: check_csv(n, data, ts) for n, data in contents.items()}
            ratio = change_ratio(wh.last_loaded_accounts(states), read_account_pairs(contents["account.csv"]))
            if guard_trips(ratio) and not approved:
                print(json.dumps({"event": "crm_guard_tripped", "export_ts": name, "change_ratio": round(ratio, 4)}))
                wh.log(ts, folder, HELD, file_count=3, ratio=ratio,
                       error=f"change ratio {ratio:.2f} is above {THRESHOLD}; run --approve export_ts={name}")
                print(f"{name}: HELD (change ratio {ratio:.2f}); nothing loaded")
                break
            # Duplicate prevention: this export is not LOADED, so any rows already carrying its export_ts are left
            # over from a run that loaded them and died before logging. Remove them so the load cannot double them.
            wh.delete_export(ts)
            for fname, table in FILE_TABLE.items():
                rows[fname] = wh.load_csv(folder + fname, table)
                if rows[fname] != expected_rows[fname]:
                    raise LoaderError(f"{fname}: loaded {rows[fname]} rows, the file has {expected_rows[fname]}")
            # Two loaders running at once (a manual run during a scheduled one) would each delete, then both load:
            # the tables would hold the export twice. The count catches that, the export is removed and retried.
            in_tables = wh.count_export(ts)
            if in_tables != expected_rows:
                raise LoaderError(f"tables hold {in_tables} rows for this export, the files have {expected_rows}: "
                                  "another loader may be running")
            wh.log(ts, folder, LOADED, file_count=3, rows=rows, ratio=ratio, approved=approved)
            states[ts] = State(LOADED, approved)
            print(f"{name}: LOADED {rows}" + (f" (change ratio {ratio:.2f})" if ratio is not None else " (first export)"))
        except Exception as exc:  # noqa: BLE001 - any failure must clean up and be logged
            wh.delete_export(ts)
            wh.log(ts, folder, FAILED, file_count=3, ratio=ratio, approved=approved, error=str(exc)[:1000])
            print(f"{name}: FAILED, rows removed, will retry next run: {exc}")
            failed = True
            break
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Load CRM export folders from GCS into BigQuery raw_crm.")
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--prefix", default="crm")
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--dataset", default=DEFAULT_DATASET)
    ap.add_argument("--location", default=DEFAULT_LOCATION)
    ap.add_argument("--approve", metavar="export_ts=<ts>", help="release a HELD export")
    args = ap.parse_args(argv)
    return run(args.bucket, args.prefix, args.project, args.dataset, args.location, args.approve)


if __name__ == "__main__":
    sys.exit(main())
