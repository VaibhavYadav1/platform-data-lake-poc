#!/usr/bin/env python3
"""E11 evidence: prove a failed build leaves wh_<env> exactly as it was (AT-29).

  1. Before:  wh_fingerprint.py snapshot --env dev --out evidence/before.json
  2. Run a micro-batch that fails mid-build (see below).
  3. After:   wh_fingerprint.py compare  --env dev --before evidence/before.json --out evidence/after.json

A snapshot holds, for every table in wh_<env> and sec_<env>, a fingerprint of all its rows

    SELECT BIT_XOR(FARM_FINGERPRINT(TO_JSON_STRING(t))), COUNT(*) FROM <table> AS t

(facts get a partition filter that covers every date, because wh requires one), and which row
access policies exist. `compare` takes a fresh snapshot and fails (exit 1) if any fingerprint
changed, a table appeared or went missing, or a row policy was lost. The two JSON files are the
evidence for the gate, together with the alert email and the workflow's run log.

Forcing the failure (micro-batch workflow, dev):
  gcloud workflows run poc-micro-batch-dev --location us-central1 \\
    --data='{"dbt_vars": "{force_fail: true}"}'
The workflow must end FAILED, and `compare` must pass. Then run a normal micro-batch:
  gcloud workflows run poc-micro-batch-dev --location us-central1 --data='{}'
and check it publishes (a new ops_<env>.publish_log row).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "orchestration" / "publish"))
import publish  # noqa: E402  (BigQueryRunner, config, tables.yaml and policy loading)

LAYERS = ("wh", "sec")
FOREVER = "DATE '1900-01-01'"  # every date a fact can hold is on or after this


def list_tables(runner, cfg) -> list[tuple[str, str]]:
    """Every table and materialized view in wh_<env> and sec_<env>, as (dataset, table)."""
    found = []
    for layer in LAYERS:
        dataset = cfg.ds(layer)
        rows = runner.query(
            f"SELECT table_name FROM `{cfg.project}.{dataset}`.INFORMATION_SCHEMA.TABLES "
            "WHERE table_type IN ('BASE TABLE', 'MATERIALIZED VIEW') ORDER BY table_name"
        )
        found += [(dataset, r["table_name"]) for r in rows]
    return found


def fingerprint_sql(project: str, dataset: str, table: str, partition_column: str | None) -> str:
    where = f" WHERE {partition_column} >= {FOREVER}" if partition_column else ""
    return (
        "SELECT BIT_XOR(FARM_FINGERPRINT(TO_JSON_STRING(t))) AS fingerprint, COUNT(*) AS n "
        f"FROM `{project}.{dataset}.{table}` AS t{where}"
    )


def snapshot(runner, cfg, tables, taken_at: str | None = None) -> dict:
    partition = {t.name: t.partition_column for t in tables if t.is_fact}
    result = {}
    for dataset, table in list_tables(runner, cfg):
        row = runner.query(fingerprint_sql(cfg.project, dataset, table, partition.get(table)))[0]
        fp = row["fingerprint"]
        result[f"{dataset}.{table}"] = {"fingerprint": None if fp is None else int(fp), "rows": int(row["n"])}
    policies = sorted(
        f"{table}:{name}" for table, name in publish.policy_names_present(runner, cfg, "wh")
    )
    return {
        "env": cfg.env,
        "taken_at": taken_at or dt.datetime.now(dt.timezone.utc).isoformat(),
        "tables": result,
        "policies": policies,
    }


def compare(before: dict, after: dict, expected_policies: list[str] | None = None) -> dict:
    """What changed between two snapshots. Empty lists everywhere means wh is untouched."""
    b, a = before["tables"], after["tables"]
    changed = sorted(t for t in set(b) & set(a) if b[t] != a[t])
    expected = set(expected_policies or [])
    return {
        "changed": changed,
        "added": sorted(set(a) - set(b)),
        "removed": sorted(set(b) - set(a)),
        "policies_lost": sorted(set(before["policies"]) - set(after["policies"])),
        "policies_missing": sorted(expected - set(after["policies"])),
    }


def expected_policies(tables, policies) -> list[str]:
    """table:policy for every tenant-scoped table in wh and every policy file."""
    return sorted(f"{t.name}:{p.name}" for t in tables if t.tenant_scoped and t.dataset == "wh" for p in policies)


def passed(report: dict) -> bool:
    return not any(report.values())


def render(before: dict, after: dict, report: dict) -> str:
    lines = [f"wh fingerprints: {before['taken_at']}  ->  {after['taken_at']}"]
    for name in sorted(after["tables"]):
        was = before["tables"].get(name)
        now = after["tables"][name]
        mark = "CHANGED" if name in report["changed"] else ("NEW" if was is None else "same")
        lines.append(f"  {mark:8} {name}  rows {was['rows'] if was else '-'} -> {now['rows']}")
    for key, title in (("removed", "REMOVED tables"), ("policies_lost", "LOST row policies"),
                       ("policies_missing", "MISSING row policies")):
        for item in report[key]:
            lines.append(f"  {title}: {item}")
    lines.append("RESULT: " + ("PASS, wh is exactly as it was" if passed(report) else "FAIL"))
    return "\n".join(lines)


# ------------------------------------------------------------------------------ command line
def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["snapshot", "compare"])
    ap.add_argument("--env", required=True)
    ap.add_argument("--config", type=Path, help="default: orchestration/publish/config.<env>.yaml")
    ap.add_argument("--tables", type=Path, default=ROOT / "orchestration" / "publish" / "tables.yaml")
    ap.add_argument("--policies-dir", type=Path, default=ROOT / "orchestration" / "publish" / "policies")
    ap.add_argument("--before", type=Path, help="compare: the snapshot taken before the failed run")
    ap.add_argument("--out", type=Path, help="where to write the snapshot")
    return ap.parse_args(argv)


def main(argv=None, runner=None) -> int:
    args = parse_args(argv)
    cfg = publish.load_config(args.config or ROOT / "orchestration" / "publish" / f"config.{args.env}.yaml")
    if cfg.env != args.env:
        print(f"config environment {cfg.env!r} does not match --env {args.env!r}", file=sys.stderr)
        return 2
    tables, _objects = publish.load_tables(args.tables)
    runner = runner or publish.BigQueryRunner(cfg.project)

    taken = snapshot(runner, cfg, tables)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(taken, indent=2), encoding="utf-8")
    if args.command == "snapshot":
        print(f"snapshot of {len(taken['tables'])} tables, {len(taken['policies'])} row policies")
        return 0

    if not args.before:
        print("compare needs --before", file=sys.stderr)
        return 2
    before = json.loads(args.before.read_text(encoding="utf-8"))
    policies = publish.load_policies(args.policies_dir) if args.policies_dir.is_dir() else []
    report = compare(before, taken, expected_policies(tables, policies))
    print(render(before, taken, report))
    return 0 if passed(report) else 1


if __name__ == "__main__":
    sys.exit(main())
