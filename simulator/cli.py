"""Command line: python -m simulator seed|batch|crm-export|case-events|tick. probe and revoke/grant come with A8, AT-25."""

import argparse
import json
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Settings
from .crm_export import CRMExportError, CRMState, generate_export, upload_to_gcs, write_export_folder
from .db import connect
from .seed import SeedError, seed
from .state import snapshot

EXPECTED = Path(__file__).resolve().parent / "expected"
DEFAULT_PROJECT = "gks-datalake-poc2-dev"


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

    # Case events command (A7)
    ce = sub.add_parser("case-events", help="publish case events to Pub/Sub (task A7)")
    ce.add_argument("--topic", required=True, help="full topic path: projects/PROJECT/topics/TOPIC")
    ce.add_argument("--count", type=int, default=5, help="number of events to publish (default: 5)")
    ce.add_argument("--seed", type=int, help="random seed for reproducibility")

    # Tick command (A8)
    t = sub.add_parser("tick", help="run one continuous-mode tick (task A8)")
    t.add_argument("--rate", type=float, help="rate multiplier (default: from RATE env var, or 1.0)")

    for name, verb in (("grant", "add"), ("revoke", "remove")):
        a = sub.add_parser(name, help=f"{verb} one g2.store_access row: this principal may see this CRM account (D3, D6)")
        a.add_argument("--principal", required=True, help="email, as SESSION_USER() returns it")
        a.add_argument("--account", required=True, help="CRM account id, e.g. ACC00001")

    sa = sub.add_parser("store-access-seed", help="grant the POC D test rows once, after seed (D3)")
    sa.add_argument("--project", default=DEFAULT_PROJECT, help="project in the service account emails")
    sa.add_argument("--dry-run", action="store_true", help="print the rows, change nothing")

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

    # Case events command (A7)
    if args.command == "case-events":
        try:
            from .case_events import publish_case_events

            rng = random.Random(args.seed) if args.seed else random.Random()
            print(f"Publishing {args.count} case events to {args.topic}")
            
            count = publish_case_events(args.topic, args.count, rng)
            
            print(f"✅ Published {count} messages successfully")
            if count > args.count:
                print(f"   (includes {count - args.count} duplicates for DQ35 testing)")
            return 0

        except ImportError as e:
            print(f"error: google-cloud-pubsub not installed: {e}")
            return 1
        except Exception as e:
            print(f"error: {e}")
            import traceback
            traceback.print_exc()
            return 1

    if args.command == "tick":
        return run_tick_command(args)

    if args.command == "store-access-seed" and args.dry_run:  # prints the rows, needs no database
        return run_store_access(None, args.command, project=args.project, dry_run=True)

    # G2 database commands (seed, batch, grant, revoke, store-access-seed)
    from .batches import BatchError, run_batch
    from .seed import SeedError, seed
    from .state import snapshot

    settings = Settings.from_env()
    print(f"G2: {settings.describe()}")
    try:
        with connect(settings) as conn:
            if args.command in ("grant", "revoke", "store-access-seed"):
                return run_store_access(conn, args.command, principal=getattr(args, "principal", None),
                                        account=getattr(args, "account", None),
                                        project=getattr(args, "project", DEFAULT_PROJECT),
                                        dry_run=getattr(args, "dry_run", False))
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


def run_tick_command(args, env=None):
    """`tick`: settings from the environment, as the Cloud Run job sets them (guide 10.6)."""
    from .tick import TickError, run_tick

    env = os.environ if env is None else env
    rate = args.rate if args.rate is not None else float(env.get("RATE", "1.0"))
    settings = Settings.from_env(env)
    print(f"G2: {settings.describe()}")
    try:
        with connect(settings) as conn:
            result = run_tick(conn, rate=rate, case_topic=env.get("CASE_TOPIC") or None,
                              g2dl_project=env.get("G2DL_PROJECT") or None, crm_bucket=env.get("CRM_BUCKET") or None,
                              crm_prefix=env.get("CRM_PREFIX", "crm"))
    except TickError as e:
        print(f"error: {e}")
        return 1
    print(result.summary())
    print(json.dumps({"opened": result.opened, "updated": result.updated, "closed": result.closed,
                      "deleted": result.deleted, "moved_device": result.moved_device, "planted": result.planted}))
    return 0


def run_store_access(conn, command, principal=None, account=None, project=None, dry_run=False):
    """Placeholder for store access commands (grant, revoke, store-access-seed)."""
    print(f"error: {command} command not yet implemented (task AT-25)")
    return 1

