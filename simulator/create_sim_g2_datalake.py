"""Create the sim_g2_datalake dataset and its three tables (POC A, task A9).

Tables:
  wheel          one row per cart wheel, written once by the simulator's seed
  wheel_event    one row per wheel signal, appended every tick by a load job; partitioned on DATE(event_ts)
  derived_alert  written hourly by the scheduled query in sql/sim_g2_datalake/derived_alert.sql, never by the simulator

Columns, partitioning and clustering follow GKS-POC-Phase2-schema.html (the plan gives column names; types, ids and
_loaded_at are proposed there). The script is idempotent and mirrors loaders/crm/create_raw_crm.py: a missing dataset
or table is created; an existing table is never altered: a difference is reported and the script exits with status 1.
Terraform (module sim_g2_datalake) owns the scheduled query and IAM, not these tables.

Settings come from the environment (see simulator/config.py): G2DL_PROJECT (else GCP_PROJECT), G2DL_DATASET,
G2DL_LOCATION. Flags override them.

Usage:
  python -m simulator.create_sim_g2_datalake --dry-run
  python -m simulator.create_sim_g2_datalake --project gks-datalake-poc2-dev
  python -m simulator.create_sim_g2_datalake --print-schema wheel_event     # JSON in bq format, no GCP access
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

from .config import LakeSettings

LABELS = {"poc": "a", "layer": "source", "source": "sim_g2_datalake"}


@dataclass(frozen=True)
class Col:
    name: str
    type: str
    mode: str = "NULLABLE"
    description: str = ""


@dataclass(frozen=True)
class Table:
    description: str
    columns: tuple[Col, ...]
    partition_field: str | None = None   # day partition on this column
    cluster_by: tuple[str, ...] = field(default_factory=tuple)


TABLES: dict[str, Table] = {
    "wheel": Table(
        description="One row per cart wheel (stand-in for the client's g2_datalake). Written once by the simulator seed.",
        columns=(
            Col("wheel_id", "STRING", "REQUIRED", "Wheel key: W and 5 digits, e.g. W00001."),
            Col("g2_store_id", "STRING", "REQUIRED", "G2 store_id of the store the wheel belongs to."),
            Col("cart_id", "STRING", "REQUIRED", "Cart the wheel is fitted to: C and 5 digits."),
            Col("installed_at", "TIMESTAMP", "REQUIRED", "When the wheel was fitted."),
            Col("status", "STRING", "REQUIRED", "ACTIVE or INACTIVE."),
        ),
    ),
    "wheel_event": Table(
        description=("What each wheel reports: lock, unlock, exit attempt, low battery. Appended every tick with one load "
                     "job (WRITE_APPEND). Duplicates possible; fct_wheel_event removes them on event_id."),
        columns=(
            Col("event_id", "STRING", "REQUIRED", "Event key: a UUID."),
            Col("wheel_id", "STRING", "REQUIRED", "The wheel. About 0.5% name an unknown wheel (DQ43)."),
            Col("event_type", "STRING", "REQUIRED", "LOCK, UNLOCK, EXIT_ATTEMPT or LOW_BATTERY."),
            Col("event_ts", "TIMESTAMP", "REQUIRED", "When the wheel sent it. Partition column."),
            Col("_loaded_at", "TIMESTAMP", "REQUIRED", "When the simulator's load job wrote the row."),
        ),
        partition_field="event_ts",
        cluster_by=("wheel_id",),
    ),
    "derived_alert": Table(
        description=("A wheel with 3 or more EXIT_ATTEMPT events in a clock hour. Appended hourly by a scheduled query "
                     "(sql/sim_g2_datalake/derived_alert.sql). Never written by the simulator."),
        columns=(
            Col("derived_alert_id", "STRING", "REQUIRED", "<wheel_id>-<yyyymmddThh> of the window start."),
            Col("wheel_id", "STRING", "REQUIRED", "The wheel."),
            Col("g2_store_id", "STRING", "NULLABLE", "From wheel; NULL for an unknown wheel."),
            Col("alert_type", "STRING", "REQUIRED", "Always CART_EXIT_ATTEMPTS."),
            Col("window_start", "TIMESTAMP", "REQUIRED", "Start of the clock hour. Partition column."),
            Col("window_end", "TIMESTAMP", "REQUIRED", "End of the clock hour (exclusive)."),
            Col("exit_attempt_count", "INT64", "REQUIRED", "Distinct EXIT_ATTEMPT events in the window."),
            Col("created_at", "TIMESTAMP", "REQUIRED", "The scheduled run's @run_time."),
        ),
        partition_field="window_start",
    ),
}

# BigQuery reports the legacy names; map both spellings to one for comparing an existing table with the definition.
_TYPE_ALIASES = {"INT64": "INTEGER", "FLOAT64": "FLOAT", "BOOL": "BOOLEAN", "STRUCT": "RECORD"}


def _norm_type(t: str) -> str:
    return _TYPE_ALIASES.get(t.upper(), t.upper())


def schema_fields(table: Table):
    from google.cloud import bigquery
    return [bigquery.SchemaField(name=c.name, field_type=c.type, mode=c.mode, description=c.description)
            for c in table.columns]


def schema_json(table: Table) -> list[dict]:
    """The schema in the JSON format of `bq mk --schema` and the console."""
    return [f.to_api_repr() for f in schema_fields(table)]


def build_table(project: str, dataset: str, name: str):
    from google.cloud import bigquery
    spec = TABLES[name]
    table = bigquery.Table(f"{project}.{dataset}.{name}", schema=schema_fields(spec))
    table.description = spec.description
    table.labels = dict(LABELS)
    if spec.partition_field:
        table.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY,
                                                            field=spec.partition_field)
    if spec.cluster_by:
        table.clustering_fields = list(spec.cluster_by)
    return table


def schema_drift(existing, spec: Table) -> list[str]:
    """Differences in column name, type and mode between a table that exists and the definition."""
    have = {f.name: (_norm_type(f.field_type), f.mode) for f in existing.schema}
    want = {c.name: (_norm_type(c.type), c.mode) for c in spec.columns}
    problems = []
    for name, w in want.items():
        if name not in have:
            problems.append(f"missing column {name}")
        elif have[name] != w:
            problems.append(f"column {name}: has {have[name][0]} {have[name][1]}, expected {w[0]} {w[1]}")
    for name in have:
        if name not in want:
            problems.append(f"extra column {name}")
    return problems


def ensure_dataset(client, project: str, dataset: str, location: str) -> str:
    from google.cloud import bigquery
    from google.cloud.exceptions import NotFound
    ref = bigquery.Dataset(f"{project}.{dataset}")
    ref.location = location
    ref.friendly_name = "Simulated G2 data lake"
    ref.description = ("POC A: stand-in for the client's g2_datalake (wheel, wheel_event, derived_alert), written by "
                       "the source simulator and read in place by dbt. Shared by dev and int.")
    ref.labels = dict(LABELS)
    try:
        client.get_dataset(ref)
        return "exists"
    except NotFound:
        client.create_dataset(ref)
        return "created"


def run(project: str, dataset: str, location: str, dry_run: bool) -> int:
    if dry_run:
        print(f"[dry run] dataset {project}.{dataset} in {location}")
        for name, spec in TABLES.items():
            part = f", partition {spec.partition_field}" if spec.partition_field else ""
            clus = f", cluster {list(spec.cluster_by)}" if spec.cluster_by else ""
            print(f"[dry run] table {name}: {len(spec.columns)} columns{part}{clus}")
        return 0

    from google.cloud import bigquery
    from google.cloud.exceptions import NotFound
    client = bigquery.Client(project=project, location=location)
    print(f"dataset {project}.{dataset}: {ensure_dataset(client, project, dataset, location)}")
    failed = False
    for name, spec in TABLES.items():
        try:
            existing = client.get_table(f"{project}.{dataset}.{name}")
        except NotFound:
            client.create_table(build_table(project, dataset, name))
            print(f"table {name}: created")
            continue
        problems = schema_drift(existing, spec)
        if problems:
            failed = True
            print(f"table {name}: EXISTS but differs from the definition (not changed):")
            for p in problems:
                print(f"    - {p}")
        else:
            print(f"table {name}: exists, schema matches")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    lake = LakeSettings.from_env()
    ap = argparse.ArgumentParser(description="Create the sim_g2_datalake dataset and its tables.")
    ap.add_argument("--project", default=lake.project)
    ap.add_argument("--location", default=lake.location)
    ap.add_argument("--dataset", default=lake.dataset)
    ap.add_argument("--dry-run", action="store_true", help="show what would be created; no GCP calls")
    ap.add_argument("--print-schema", choices=sorted(TABLES), metavar="TABLE",
                    help="print one table's schema as JSON and exit; no GCP calls (" + ", ".join(sorted(TABLES)) + ")")
    args = ap.parse_args(argv)
    if args.print_schema:
        print(json.dumps(schema_json(TABLES[args.print_schema]), indent=2))
        return 0
    return run(args.project, args.dataset, args.location, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
