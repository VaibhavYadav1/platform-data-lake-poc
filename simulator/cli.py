"""Command line: python -m simulator seed|batch. tick, crm-export, probe and revoke/grant come with A7, A8, B2, AT-25."""

import argparse
import json
from pathlib import Path

from .batches import BatchError, run_batch
from .config import Settings
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
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
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
