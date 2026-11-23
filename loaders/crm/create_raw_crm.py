"""Create the raw_crm dataset and its four tables (POC B, task B3).

Tables:
  account_landing, store_landing, work_order_landing   one row per record per loaded export (append only)
  load_log                                             one row per load attempt of an export folder

The loader (poc-crm-loader) loads the CSV files with WRITE_APPEND and an explicit schema, so these tables must exist
before the first load. Only the key and export_ts are REQUIRED in the landing tables, so a bad row still loads and dbt
flags it. The landing tables are partitioned on DATE(export_ts), because the loader deletes a failed folder's rows by
export_ts. Partitioning, clustering and the extra load_log columns are proposed: the plan gives only column lists.
Column descriptions follow GKS-POC-Phase2-schema.html.

The script is idempotent. A missing dataset or table is created. An existing table is never altered: if its columns
differ from the definition, the difference is reported and the script exits with status 1.

Usage:
  python create_raw_crm.py --project gks-datalake-poc2-dev --pii-tag <policy tag resource name>
  python create_raw_crm.py --project gks-datalake-poc2-dev --dry-run
  python create_raw_crm.py --print-schema account_landing          # JSON in bq format, no GCP access needed
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

from google.cloud import bigquery
from google.cloud.exceptions import NotFound

DEFAULT_PROJECT = "gks-datalake-poc2-dev"
DEFAULT_LOCATION = "us-central1"
DEFAULT_DATASET = "raw_crm"
LABELS = {"poc": "b", "layer": "raw", "source": "crm"}


@dataclass(frozen=True)
class Col:
    name: str
    type: str
    mode: str = "NULLABLE"
    description: str = ""
    pii: bool = False          # direct personal data: gets the pii_direct policy tag when one is given
    default: str | None = None  # default value expression


@dataclass(frozen=True)
class Table:
    description: str
    columns: tuple[Col, ...]
    partition_field: str | None = None   # day partition on this column
    cluster_by: tuple[str, ...] = field(default_factory=tuple)


EXPORT_TS = Col("export_ts", "TIMESTAMP", "REQUIRED", "The export the row came in. Partition column.")
UPDATED_AT = Col("updated_at", "TIMESTAMP", "NULLABLE", "Last change in the CRM. The watermark of the merge.")

TABLES: dict[str, Table] = {
    "account_landing": Table(
        description=(
            "Every account export exactly as delivered, typed. Append only: a failed folder's rows are deleted by "
            "export_ts and the folder is retried (B3)."
        ),
        columns=(
            Col("account_id", "STRING", "REQUIRED", "CRM account id, from the file."),
            Col("account_name", "STRING", description="Company name, from the file."),
            Col("customer_type_code", "STRING",
                description="CRM option-set code: 100000000 Customer, 100000001 Vendor, 100000002 Partner, 100000003 Prospect."),
            Col("status", "STRING", description="Active or Inactive."),
            Col("parent_account_id", "STRING", description="Parent account; empty becomes NULL in staging."),
            Col("primary_contact_name", "STRING", pii=True,
                description="Contact person's name. Policy tag pii_direct. Dropped in staging."),
            Col("primary_contact_email", "STRING", pii=True,
                description="Contact person's email. Policy tag pii_direct. Becomes primary_contact_token in staging."),
            UPDATED_AT,
            EXPORT_TS,
        ),
        partition_field="export_ts",
        cluster_by=("account_id",),
    ),
    "store_landing": Table(
        description="Every CRM store export exactly as delivered, typed. Append only, as account_landing.",
        columns=(
            Col("crm_store_id", "STRING", "REQUIRED", "CRM store record id, from the file."),
            Col("account_id", "STRING", description="Account that owns the store."),
            Col("g2_store_id", "STRING", description="G2 store_id the record maps to."),
            Col("status", "STRING", description="Active or Inactive. Only an Active record assigns a tenant."),
            UPDATED_AT,
            EXPORT_TS,
        ),
        partition_field="export_ts",
        cluster_by=("crm_store_id",),
    ),
    "work_order_landing": Table(
        description="Every work-order export exactly as delivered, typed. Append only, as account_landing.",
        columns=(
            Col("work_order_id", "STRING", "REQUIRED", "Work order id, from the file."),
            Col("account_id", "STRING", description="Account the work is for."),
            Col("crm_store_id", "STRING", description="CRM store record where the work happens."),
            Col("g2_device_id", "STRING", description="G2 device the work is on. Empty when the work is not on one device."),
            Col("work_type", "STRING", description="INSTALL, REPAIR, INSPECTION or REMOVAL (proposed)."),
            Col("status", "STRING", description="OPEN, IN_PROGRESS, CLOSED or CANCELLED (proposed)."),
            Col("opened_at", "TIMESTAMP", description="When the work order was opened."),
            Col("closed_at", "TIMESTAMP", description="When it was closed or cancelled. Empty while open."),
            UPDATED_AT,
            EXPORT_TS,
        ),
        partition_field="export_ts",
        cluster_by=("work_order_id",),
    ),
    "load_log": Table(
        description=(
            "One row per load attempt of an export folder. Makes the loader safe to re-run: LOADED folders are "
            "skipped, a HELD folder blocks later ones, a FAILED one is retried. The newest row per export_ts is the "
            "folder's state."
        ),
        columns=(
            Col("export_ts", "TIMESTAMP", "REQUIRED", "The export folder's time."),
            Col("folder", "STRING", "REQUIRED", "gs://<bucket>/crm/export_ts=<...>/"),
            Col("status", "STRING", "REQUIRED", "LOADED, HELD or FAILED."),
            Col("file_count", "INT64", description="Files listed in the manifest (3)."),
            Col("account_rows", "INT64", description="Rows loaded from account.csv; NULL when nothing was loaded."),
            Col("store_rows", "INT64", description="Rows loaded from store.csv."),
            Col("work_order_rows", "INT64", description="Rows loaded from work_order.csv."),
            Col("change_ratio", "FLOAT64",
                description="Changed accounts divided by accounts in the previous loaded export (B5). "
                            "Above 0.5 means HELD (DQ42). NULL for the first export."),
            Col("approved", "BOOL", "REQUIRED", "True when this attempt ran with --approve for a HELD folder.",
                default="FALSE"),
            Col("error_message", "STRING", description="Why the folder failed or was held."),
            Col("loader_execution", "STRING", description="Cloud Run job execution name."),
            Col("logged_at", "TIMESTAMP", "REQUIRED", "When the row was written."),
        ),
    ),
}

# BigQuery reports the legacy names; map both spellings to one for comparing an existing table with the definition.
_TYPE_ALIASES = {"INT64": "INTEGER", "FLOAT64": "FLOAT", "BOOL": "BOOLEAN", "STRUCT": "RECORD"}


def _norm_type(t: str) -> str:
    return _TYPE_ALIASES.get(t.upper(), t.upper())


def schema_fields(table: Table, pii_tag: str | None) -> list[bigquery.SchemaField]:
    """The table's columns as BigQuery schema fields; contact columns get the policy tag when pii_tag is set."""
    out = []
    for c in table.columns:
        kwargs = dict(name=c.name, field_type=c.type, mode=c.mode, description=c.description)
        if c.default is not None:
            kwargs["default_value_expression"] = c.default
        if c.pii and pii_tag:
            kwargs["policy_tags"] = bigquery.PolicyTagList(names=[pii_tag])
        out.append(bigquery.SchemaField(**kwargs))
    return out


def schema_json(table: Table, pii_tag: str | None) -> list[dict]:
    """The same schema in the JSON format of `bq mk --schema` and the console."""
    return [f.to_api_repr() for f in schema_fields(table, pii_tag)]


def build_table(project: str, dataset: str, name: str, pii_tag: str | None) -> bigquery.Table:
    spec = TABLES[name]
    table = bigquery.Table(f"{project}.{dataset}.{name}", schema=schema_fields(spec, pii_tag))
    table.description = spec.description
    table.labels = dict(LABELS)
    if spec.partition_field:
        table.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field=spec.partition_field)
    if spec.cluster_by:
        table.clustering_fields = list(spec.cluster_by)
    return table


def schema_drift(existing: bigquery.Table, spec: Table) -> list[str]:
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


def ensure_dataset(client: bigquery.Client, project: str, dataset: str, location: str) -> str:
    ref = bigquery.Dataset(f"{project}.{dataset}")
    ref.location = location
    ref.friendly_name = "CRM landing"
    ref.description = ("POC B: every CRM export as delivered (account, store, work order) plus load_log. "
                       "Shared by dev and int; only dev runs the loader.")
    ref.labels = dict(LABELS)
    try:
        client.get_dataset(ref)
        return "exists"
    except NotFound:
        client.create_dataset(ref)
        return "created"


def run(project: str, dataset: str, location: str, pii_tag: str | None, dry_run: bool) -> int:
    if not pii_tag:
        print("note: no --pii-tag given; primary_contact_name and primary_contact_email are created WITHOUT the "
              "pii_direct policy tag (task D9).", file=sys.stderr)
    if dry_run:
        print(f"[dry run] dataset {project}.{dataset} in {location}")
        for name, spec in TABLES.items():
            part = f", partition {spec.partition_field}" if spec.partition_field else ""
            clus = f", cluster {list(spec.cluster_by)}" if spec.cluster_by else ""
            print(f"[dry run] table {name}: {len(spec.columns)} columns{part}{clus}")
        return 0

    client = bigquery.Client(project=project, location=location)
    print(f"dataset {project}.{dataset}: {ensure_dataset(client, project, dataset, location)}")
    failed = False
    for name, spec in TABLES.items():
        full = f"{project}.{dataset}.{name}"
        try:
            existing = client.get_table(full)
        except NotFound:
            client.create_table(build_table(project, dataset, name, pii_tag))
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
    ap = argparse.ArgumentParser(description="Create the raw_crm dataset and its tables.")
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--location", default=DEFAULT_LOCATION)
    ap.add_argument("--dataset", default=DEFAULT_DATASET)
    ap.add_argument("--pii-tag", default=None,
                    help="resource name of the pii_direct policy tag: "
                         "projects/<p>/locations/<l>/taxonomies/<id>/policyTags/<id>")
    ap.add_argument("--dry-run", action="store_true", help="show what would be created; no GCP calls")
    ap.add_argument("--print-schema", choices=sorted(TABLES), metavar="TABLE",
                    help="print one table's schema as JSON and exit; no GCP calls (" + ", ".join(sorted(TABLES)) + ")")
    args = ap.parse_args(argv)

    if args.print_schema:
        print(json.dumps(schema_json(TABLES[args.print_schema], args.pii_tag), indent=2))
        return 0
    return run(args.project, args.dataset, args.location, args.pii_tag, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
