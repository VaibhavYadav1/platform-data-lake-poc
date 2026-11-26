"""D9: put policy tags on personal-data columns of the tables Datastream creates in raw_g2.

Terraform can't own those schemas (Datastream creates the tables), so this script sets policyTags through the
tables API. It is idempotent: re-run it whenever a table is recreated. raw_crm is tagged in Terraform instead.

    python scripts/security/tag_raw_columns.py --pii-direct-tag projects/P/locations/us-central1/taxonomies/T/policyTags/X
        [--with-indirect --pii-indirect-tag ...] [--dry-run] [--project gks-datalake-poc2-dev]

Tag names come from the Terraform policy_tags module outputs (or env PII_DIRECT_TAG / PII_INDIRECT_TAG).
"""
from __future__ import annotations

import argparse
import copy
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_lib import log  # noqa: E402

# pii-inventory.md section 4: (dataset, table, column, tag kind)
DIRECT = [
    ("raw_g2", "g2_users", "user_name", "pii_direct"),
    ("raw_g2", "g2_users", "email", "pii_direct"),
    ("raw_g2", "g2_store_access", "principal", "pii_direct"),
]
INDIRECT = [  # only with --with-indirect: the pii_indirect tag is still a decision to confirm
    ("raw_g2", "g2_users", "user_id", "pii_indirect"),
    ("raw_g2", "g2_alert_incidents", "assigned_user_id", "pii_indirect"),
    ("raw_g2", "g2_alert_history", "changed_by_user_id", "pii_indirect"),
]


class TagError(Exception):
    pass


def wanted_tags(direct_tag: str, indirect_tag: str | None, with_indirect: bool) -> dict:
    """{(dataset, table): {column: tag resource name}}"""
    if with_indirect and not indirect_tag:
        raise TagError("--with-indirect needs --pii-indirect-tag")
    tag_of = {"pii_direct": direct_tag, "pii_indirect": indirect_tag}
    out: dict = {}
    for ds, table, col, kind in DIRECT + (INDIRECT if with_indirect else []):
        out.setdefault((ds, table), {})[col] = tag_of[kind]
    return out


def plan_schema(schema, wanted: dict, table: str):
    """Return (new schema, changes). Refuse a missing or nested column rather than tag the wrong thing."""
    from google.cloud.bigquery import SchemaField

    names = {f.name: f for f in schema}
    missing = sorted(set(wanted) - set(names))
    if missing:
        raise TagError(f"{table}: column(s) {missing} not found; nothing changed")
    new, changes = [], []
    for f in schema:
        tag = wanted.get(f.name)
        if tag is None:
            new.append(f)
            continue
        if f.field_type in ("RECORD", "STRUCT"):
            raise TagError(f"{table}.{f.name} is a RECORD; tag its leaf fields instead")
        current = list(f.policy_tags.names) if f.policy_tags else []
        if current == [tag]:
            new.append(f)
            continue
        api = copy.deepcopy(f.to_api_repr())  # to_api_repr may share the field's own dict
        api["policyTags"] = {"names": [tag]}
        new.append(SchemaField.from_api_repr(api))
        changes.append({"table": table, "column": f.name, "from": current, "to": tag})
    return new, changes


def apply(client, project: str, wanted: dict, dry_run: bool) -> list[dict]:
    all_changes = []
    for (ds, table), cols in wanted.items():
        ref = f"{project}.{ds}.{table}"
        t = client.get_table(ref)
        new_schema, changes = plan_schema(t.schema, cols, ref)
        for c in changes:
            log("TAG_PLANNED" if dry_run else "TAG_SET", **c)
        if changes and not dry_run:
            t.schema = new_schema
            client.update_table(t, ["schema"])
        all_changes.extend(changes)
    if not all_changes:
        log("NOTHING_TO_DO", detail="every column already carries its tag")
    return all_changes


def main(argv=None, client=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", default=os.environ.get("PROJECT", "gks-datalake-poc2-dev"))
    ap.add_argument("--pii-direct-tag", default=os.environ.get("PII_DIRECT_TAG"))
    ap.add_argument("--pii-indirect-tag", default=os.environ.get("PII_INDIRECT_TAG"))
    ap.add_argument("--with-indirect", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        if not args.pii_direct_tag:
            raise TagError("--pii-direct-tag (or PII_DIRECT_TAG) is required")
        wanted = wanted_tags(args.pii_direct_tag, args.pii_indirect_tag, args.with_indirect)
        if client is None:
            from google.cloud import bigquery

            client = bigquery.Client(project=args.project)
        apply(client, args.project, wanted, args.dry_run)
        return 0
    except TagError as e:
        log("TAG_FAILED", "ERROR", message=str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
