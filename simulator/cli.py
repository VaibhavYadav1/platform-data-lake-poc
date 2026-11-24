"""Command line: python -m simulator seed|batch|crm-export. tick, probe and revoke/grant come with A7, A8, AT-25."""

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .batches import BatchError, run_batch
from .config import Settings
from .crm_export import CRMExportError, CRMState, generate_export, upload_to_gcs, write_export_folder
from .db import connect
from .seed import SeedError, seed
from .state import snapshot

EXPECTED = Path(__file__).resolve().parent / "expected"


def expected_path(n):
    return EXPECTED / f"batch_{n}.json"


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="python -m simulator", description="poc-source-simulator, scripted mode")
    sub = parser.add_subparsers(dest="command", required=True)
    
    s = sub.add_parser("seed", help="load the frozen POC 1 batch and the probe rows into an empty G2")
    s.add_argument("--batch", required=True, help="the batch folder from docs/poc2/baseline.md")
    s.add_argument("--reset", action="store_true", help="local database only: empty the 11 tables first")
    
    b = sub.add_parser("batch", help="apply one scripted change batch, then compare with expected/batch_<n>.json")
    b.add_argument("--n", type=int, required=True, choices=[1, 2, 3])
    b.add_argument("--write-expected", action="store_true",
                   help="write expected/batch_<n>.json from the result instead of comparing with it")
    
    c = sub.add_parser("crm-export", help="generate CRM export snapshots (task B2)")
    c.add_argument("--bucket", help="GCS bucket name (without gs://)")
    c.add_argument("--prefix", default="crm", help="folder prefix in bucket (default: crm)")
    c.add_argument("--local-dir", type=Path, help="write to local directory instead of GCS")
    c.add_argument("--count", type=int, default=1, help="number of hourly exports to generate")
    c.add_argument("--change-rate", type=float, default=0.1, help="change rate per export (0.0-1.0)")
    c.add_argument("--big-change", action="store_true", help="force >50%% change (for AT-21 testing)")
    c.add_argument("--plant-issues", action="store_true", help="plant DQ issues for testing")
    c.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    c.add_argument("--start-time", help="first export timestamp (YYYYMMDDTHHMMSSZ), default: now")
    
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    
    # CRM export command (B2)
    if args.command == "crm-export":
        try:
            # Parse start time
            if args.start_time:
                start_time = datetime.strptime(args.start_time, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            else:
                start_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            
            # Validate arguments
            if not args.bucket and not args.local_dir:
                print("error: either --bucket or --local-dir is required")
                return 1
            
            print(f"Generating {args.count} CRM export(s) starting at {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            if args.big_change:
                print("⚠️  Big change mode: >50% change rate (for AT-21 testing)")
            
            # Initialize CRM state
            state = CRMState.initialize(n_accounts=50, n_stores=100, seed=args.seed)
            
            # Generate exports
            for i in range(args.count):
                export_time = start_time + timedelta(hours=i)
                print(f"\nExport {i + 1}/{args.count}: {export_time.strftime('%Y%m%dT%H%M%SZ')}")
                
                # Generate CSV content
                csv_files = generate_export(
                    state=state,
                    export_time=export_time,
                    change_rate=args.change_rate,
                    big_change=args.big_change and i == args.count - 1,  # Apply big change to last export
                    plant_issues=args.plant_issues,
                )
                
                # Write to destination
                if args.local_dir:
                    folder = write_export_folder(args.local_dir, export_time, csv_files)
                    print(f"  ✓ Written to {folder}")
                else:
                    path = upload_to_gcs(args.bucket, args.prefix, export_time, csv_files)
                    print(f"  ✓ Uploaded to {path}")
                
                # Print stats
                for name, content in csv_files.items():
                    rows = content.count('\n') - 1  # Subtract header
                    print(f"    {name}: {rows} rows")
            
            print(f"\n✅ Generated {args.count} export(s) successfully")
            return 0
            
        except CRMExportError as e:
            print(f"error: {e}")
            return 1
        except Exception as e:
            print(f"error: {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    # G2 database commands (seed, batch)
    settings = Settings.from_env()
    print(f"G2: {settings.describe()}")
    try:
        with connect(settings) as conn:
            if args.command == "seed":
                seed(conn, args.batch, reset=args.reset, local=settings.is_local)
                return 0
            changes = run_batch(conn, args.n)
            result = {"batch": args.n, "changes": changes, "state": snapshot(conn)}
    except (SeedError, BatchError) as e:
        print(f"error: {e}")
        return 1

    print(json.dumps(result["changes"], indent=2))
    path = expected_path(args.n)
    if args.write_expected:
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")
        return 0
    if not path.exists():
        print(f"no {path.name} to compare with (write it with --write-expected)")
        return 0
    expected = json.loads(path.read_text(encoding="utf-8"))
    if expected != result:
        print(f"MISMATCH with {path.name}: the batch did not produce the expected state")
        for key in ("changes", "state"):
            if expected[key] != result[key]:
                print(f"  {key}: expected {json.dumps(expected[key])}\n  {key}: actual   {json.dumps(result[key])}")
        return 1
    print(f"matches {path.name}")
    return 0
