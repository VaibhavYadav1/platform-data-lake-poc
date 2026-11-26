"""
AT-15: CDC initial copy validation

Proves that the initial CDC copy is complete: for each of the 11 tables,
the count of rows in Cloud SQL equals the count of non-deleted keys in
either raw_g2 (--raw mode) or the staging views (--stg-dataset mode).

Usage:
    # Test now against raw_g2 (before A10 staging views exist)
    cloud-sql-proxy gks-datalake-poc2-dev:us-central1:poc-ops-db --port 5433 &
    python scripts/acceptance/at15_cdc_initial.py --raw

    # Real test once A10 staging views exist
    python scripts/acceptance/at15_cdc_initial.py --stg-dataset dbt_<you>_stg

Evidence: docs/poc2/evidence/at15_<timestamp>.json
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

REPO = Path(__file__).resolve().parents[2]
PROJECT = "gks-datalake-poc2-dev"
RAW_DATASET = "raw_g2"
EVIDENCE_DIR = REPO / "docs" / "poc2" / "evidence"

# Primary keys for each of the 11 tables
KEYS = {
    "brands": ["brand_id"],
    "teams": ["team_id"],
    "statuses": ["status_id"],
    "users": ["user_id"],
    "alert_types": ["alert_type_id"],
    "stores": ["store_id"],
    "device_locations": ["device_id"],
    "alert_incidents": ["incident_id"],
    "alert_history": ["history_id"],
    "store_access": ["principal", "crm_account_id"],  # sql/g2/schema.sql
    "heartbeat": ["source"],
}


def secret(name):
    """Latest version of a Secret Manager secret, read with gcloud."""
    gcloud = shutil.which("gcloud.cmd") or shutil.which("gcloud") or "gcloud"
    run = subprocess.run(
        [gcloud, "secrets", "versions", "access", "latest", f"--secret={name}", f"--project={PROJECT}"],
        capture_output=True, text=True
    )
    if run.returncode != 0:
        sys.exit(f"Could not read secret {name}: {run.stderr.strip()}")
    return run.stdout.strip()


def pg_scalar(sql, host="127.0.0.1", port=5433, db="g2"):
    """Execute a SQL query on Cloud SQL and return the first column of the first row."""
    password = secret("poc-ops-db-simulator")
    with psycopg.connect(
        host=host, port=port, dbname=db, user="simulator_user",
        password=password, connect_timeout=10
    ) as conn:
        cur = conn.cursor()
        cur.execute(sql)
        return cur.fetchone()[0]


def pause_scheduler():
    """Pause the poc-simulator-tick Cloud Scheduler job if it exists."""
    gcloud = shutil.which("gcloud.cmd") or shutil.which("gcloud") or "gcloud"
    run = subprocess.run(
        [gcloud, "scheduler", "jobs", "pause", "poc-simulator-tick",
         "--location=us-central1", f"--project={PROJECT}"],
        capture_output=True, text=True
    )
    if run.returncode != 0:
        if "NOT_FOUND" in run.stderr or "not found" in run.stderr.lower():
            print("   scheduler job poc-simulator-tick does not exist (skipped)")
            return False
        sys.exit(f"Could not pause scheduler job: {run.stderr.strip()}")
    print("   paused scheduler job poc-simulator-tick")
    return True


def resume_scheduler():
    """Resume the poc-simulator-tick Cloud Scheduler job."""
    gcloud = shutil.which("gcloud.cmd") or shutil.which("gcloud") or "gcloud"
    run = subprocess.run(
        [gcloud, "scheduler", "jobs", "resume", "poc-simulator-tick",
         "--location=us-central1", f"--project={PROJECT}"],
        capture_output=True, text=True
    )
    if run.returncode != 0:
        print(f"WARNING: Could not resume scheduler job: {run.stderr.strip()}")
    else:
        print("   resumed scheduler job poc-simulator-tick")


def wait_for_datastream(pg_port, timeout=600):
    """
    Update the heartbeat and wait for Datastream to catch up.
    Returns the beat timestamp.
    """
    print("Waiting for Datastream to catch up...")
    beat_at = pg_scalar(
        "UPDATE g2.heartbeat SET beat_at = now() WHERE source = 'simulator' RETURNING beat_at",
        port=pg_port
    )
    print(f"   Updated heartbeat at {beat_at}")

    client = bigquery.Client(project=PROJECT)
    query = f"""
        SELECT beat_at
        FROM `{PROJECT}.{RAW_DATASET}.g2_heartbeat`
        WHERE source = 'simulator' AND beat_at = TIMESTAMP('{beat_at}')
        LIMIT 1
    """
    
    start = time.time()
    while time.time() - start < timeout:
        result = list(client.query(query).result())
        if result:
            print(f"   Datastream caught up (found beat_at = {beat_at})")
            return beat_at
        time.sleep(5)
    
    sys.exit(f"Timeout: Datastream did not replicate the heartbeat after {timeout}s")


def source_count(table, pg_port):
    """Count rows in the Cloud SQL source table."""
    return pg_scalar(f"SELECT COUNT(*) FROM g2.{table}", port=pg_port)


def staged_count_from_view(client, dataset, table):
    """Count non-deleted rows from a staging view. None if the view doesn't exist (reported as FAIL)."""
    query = f"""
        SELECT COUNT(*)
        FROM `{PROJECT}.{dataset}.stg_g2__{table}`
        WHERE NOT is_deleted
    """
    try:
        result = list(client.query(query).result())
    except NotFound:
        # A missing view is a failed table, not a crash: the evidence must still list all 11
        return None
    return result[0][0]


def staged_count_from_raw(client, table, keys):
    """
    Count non-deleted rows from raw_g2 using the current-state ordering rule.
    
    This replicates the staging view logic: for each primary key, keep only
    the latest row (by source_timestamp desc, then WAL position desc), and
    count it unless it's a DELETE.
    """
    keys_str = ", ".join(keys)
    
    query = f"""
        SELECT COUNT(*) FROM (
          SELECT datastream_metadata.change_type AS ct
          FROM `{PROJECT}.{RAW_DATASET}.g2_{table}`
          QUALIFY ROW_NUMBER() OVER (
            PARTITION BY {keys_str}
            ORDER BY datastream_metadata.source_timestamp DESC,
              CAST(CONCAT('0x', SPLIT(NULLIF(datastream_metadata.sort_keys[SAFE_OFFSET(1)], ''), '/')[SAFE_OFFSET(0)]) AS INT64) DESC NULLS LAST,
              CAST(CONCAT('0x', SPLIT(NULLIF(datastream_metadata.sort_keys[SAFE_OFFSET(1)], ''), '/')[SAFE_OFFSET(1)]) AS INT64) DESC NULLS LAST
          ) = 1
        ) WHERE ct != 'DELETE'
    """
    
    try:
        client.get_table(f"{PROJECT}.{RAW_DATASET}.g2_{table}")
    except NotFound:
        # Datastream creates no table for an empty source table (g2_store_access until its first row)
        return 0
    result = list(client.query(query).result())
    return result[0][0]


def main():
    parser = argparse.ArgumentParser(description="AT-15: validate CDC initial copy")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--raw", action="store_true",
                       help="compare against raw_g2 (test mode before A10)")
    group.add_argument("--stg-dataset", metavar="NAME",
                       help="compare against staging views (real test after A10)")
    parser.add_argument("--pg-port", type=int, default=5433,
                        help="Cloud SQL Auth Proxy port (default: 5433)")
    args = parser.parse_args()

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # UTC, so the Z is true
    
    client = bigquery.Client(project=PROJECT)
    scheduler_paused = False

    try:
        # Pause the simulator
        scheduler_paused = pause_scheduler()
        
        # Wait for Datastream to catch up
        wait_for_datastream(args.pg_port)
        
        # Run comparisons
        print("\nComparing counts:")
        print(f"{'Table':<20} {'Source':>8} {'Staged':>8} {'Result'}")
        print("-" * 50)
        
        results = []
        all_match = True
        
        for table in KEYS:
            source = source_count(table, args.pg_port)
            
            if args.raw:
                staged = staged_count_from_raw(client, table, KEYS[table])
            else:
                staged = staged_count_from_view(client, args.stg_dataset, table)
            
            match = source == staged
            status = "OK" if match else ("FAIL (view missing)" if staged is None else "FAIL")
            if not match:
                all_match = False

            print(f"{table:<20} {source:>8} {'-' if staged is None else staged:>8} {status}")
            
            results.append({
                "table": table,
                "source_count": source,
                "staged_count": staged,
                "match": match
            })
        
        # Write evidence
        evidence = {
            "test": "AT-15",
            "timestamp": timestamp,
            "mode": "raw" if args.raw else f"staging:{args.stg_dataset}",
            "all_match": all_match,
            "results": results
        }
        
        evidence_file = EVIDENCE_DIR / f"at15_{timestamp}.json"
        evidence_file.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"\nEvidence written to {evidence_file.relative_to(REPO)}")
        
        if all_match:
            print("PASS: All 11 tables match")
            sys.exit(0)
        else:
            print("FAIL: Some tables do not match")
            sys.exit(1)
    
    finally:
        if scheduler_paused:
            resume_scheduler()


if __name__ == "__main__":
    main()
