#!/usr/bin/env python3
"""E5: write-audit-publish.

Copies the tested build in build_<env> into wh_<env> (and map_tenant_access into sec_<env>)
inside ONE transaction, so readers see the old version of every table or the new one, never a
mix. dbt never writes to wh_<env>; this script owns everything in it: the tables, the row access
policies, the native materialized views and the table options. Published tables are never
recreated, so their row policies stay in place (D-27, D-28).

Steps (plan, task E5):
  1. dbt did not exit 0: log PUBLISH_SKIPPED and stop. wh is untouched.
  2. For each fact, find the partitions this dbt run changed.
  3. Set-up outside the transaction (DDL cannot be in one), all idempotent: create missing
     tables, require_partition_filter on facts, new columns, row policies, native views.
  4. One transaction: replace dimensions/marts, replace the changed fact partitions, log.
  5. Checks: row counts match build; the row policies exist on every tenant-scoped table.
     A failed check exits non-zero, so the workflow fails and the alert fires.

Usage:
  publish.py --env dev [--invocation-id ID] [--dbt-exit-code N] [--all] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent

FACT_KINDS = {"fact"}
REPLACE_KINDS = {"dim", "dimension", "mart", "security"}
DATASET_LAYERS = {"wh", "sec"}


class PublishError(Exception):
    """A problem that must stop the publish with a clear message."""


def log(event: str, severity: str = "INFO", **fields) -> None:
    print(json.dumps({"severity": severity, "event": event, **fields}, default=str), flush=True)


# ------------------------------------------------------------------------------ configuration
@dataclass(frozen=True)
class Table:
    name: str
    kind: str
    dataset: str  # published layer: "wh" or "sec"
    partition_column: str | None
    tenant_scoped: bool

    @property
    def is_fact(self) -> bool:
        return self.kind in FACT_KINDS


@dataclass(frozen=True)
class Config:
    project: str
    env: str
    all_rows_principals: tuple[str, ...] = ()
    tenant_principals: tuple[str, ...] = ()
    require_policies: bool = True

    def ds(self, layer: str) -> str:
        return f"{layer}_{self.env}"


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for key in ("project", "environment"):
        if not raw.get(key):
            raise PublishError(f"{path}: missing '{key}'")
    return Config(
        project=raw["project"],
        env=raw["environment"],
        all_rows_principals=tuple(raw.get("all_rows_principals") or ()),
        tenant_principals=tuple(raw.get("tenant_principals") or ()),
        require_policies=bool(raw.get("require_policies", True)),
    )


def load_tables(path: Path) -> tuple[list[Table], list[str]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tables = []
    for entry in raw.get("tables") or []:
        name, kind = entry.get("name"), entry.get("kind")
        if not name or kind not in FACT_KINDS | REPLACE_KINDS:
            raise PublishError(f"{path}: bad table entry {entry!r}")
        dataset = entry.get("dataset", "wh")
        if dataset not in DATASET_LAYERS:
            raise PublishError(f"{path}: {name}: dataset must be one of {sorted(DATASET_LAYERS)}")
        if kind in FACT_KINDS and not entry.get("partition_column"):
            raise PublishError(f"{path}: fact {name} needs a partition_column")
        tables.append(
            Table(name, kind, dataset, entry.get("partition_column"), bool(entry.get("tenant_scoped")))
        )
    if not tables:
        raise PublishError(f"{path}: no tables listed")
    return tables, list(raw.get("objects") or [])


@dataclass(frozen=True)
class Policy:
    name: str
    template: str


_POLICY_NAME = re.compile(r"ROW ACCESS POLICY\s+(?:IF NOT EXISTS\s+)?(\w+)", re.IGNORECASE)


def load_policies(directory: Path) -> list[Policy]:
    policies = []
    for f in sorted(directory.glob("*.sql")):
        text = f.read_text(encoding="utf-8")
        m = _POLICY_NAME.search(text)
        if not m:
            raise PublishError(f"{f}: no CREATE ROW ACCESS POLICY found")
        policies.append(Policy(m.group(1), text))
    return policies


# ------------------------------------------------------------------------------ BigQuery access
class BigQueryRunner:
    """Runs SQL and returns rows as dicts. Parameters are {name: (TYPE, value-or-list)}."""

    def __init__(self, project: str):
        from google.cloud import bigquery  # imported late so tests do not need the library

        self._bq = bigquery
        self._client = bigquery.Client(project=project)

    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        bq = self._bq
        built = []
        for name, (typ, value) in (params or {}).items():
            if isinstance(value, list):
                built.append(bq.ArrayQueryParameter(name, typ, value))
            else:
                built.append(bq.ScalarQueryParameter(name, typ, value))
        job = self._client.query(sql, job_config=bq.QueryJobConfig(query_parameters=built))
        return [dict(r) for r in job.result()]


def ref(project: str, dataset: str, table: str) -> str:
    return f"`{project}.{dataset}.{table}`"


# ------------------------------------------------------------------------------ building blocks
def get_columns(runner, cfg: Config, layer: str, table: str) -> list[tuple[str, str]]:
    sql = (
        f"SELECT column_name, data_type FROM `{cfg.project}.{cfg.ds(layer)}`.INFORMATION_SCHEMA.COLUMNS "
        "WHERE table_name = @t ORDER BY ordinal_position"
    )
    rows = runner.query(sql, {"t": ("STRING", table)})
    return [(r["column_name"], r["data_type"]) for r in rows]


def changed_partitions(runner, cfg: Config, t: Table, col_type: str, invocation_id, publish_all):
    build = ref(cfg.project, cfg.ds("build"), t.name)
    if publish_all:
        rows = runner.query(f"SELECT DISTINCT {t.partition_column} AS p FROM {build}")
    else:
        rows = runner.query(
            f"SELECT DISTINCT {t.partition_column} AS p FROM {build} "
            "WHERE _dbt_invocation_id = @invocation_id",
            {"invocation_id": ("STRING", invocation_id)},
        )
    return sorted(r["p"] for r in rows if r["p"] is not None)


@dataclass
class TablePlan:
    table: Table
    columns: list[tuple[str, str]]
    dates: list = field(default_factory=list)
    date_type: str = "DATE"

    @property
    def publishes(self) -> bool:
        return (not self.table.is_fact) or bool(self.dates)


def check_schema(build_cols, wh_cols, table: str) -> list[str]:
    """Return ADD COLUMN names. A removed or retyped column stops the publish."""
    b, w = dict(build_cols), dict(wh_cols)
    removed = sorted(set(w) - set(b))
    retyped = sorted(c for c in set(b) & set(w) if b[c] != w[c])
    if removed or retyped:
        parts = []
        if removed:
            parts.append(f"removed columns {removed}")
        if retyped:
            parts.append("retyped columns " + ", ".join(f"{c} ({w[c]} to {b[c]})" for c in retyped))
        raise PublishError(
            f"{table}: build no longer matches the published table: {'; '.join(parts)}. "
            "This needs a planned migration, so nothing was published."
        )
    return [c for c, _ in build_cols if c not in w]


def render(template: str, **values) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return out


def principals_sql(principals) -> str:
    return ", ".join(f'"{p}"' for p in principals)


def policy_sql(cfg: Config, policy: Policy, table: str) -> str:
    return render(
        policy.template,
        project=cfg.project,
        env=cfg.env,
        table=table,
        all_rows_principals=principals_sql(cfg.all_rows_principals),
        tenant_principals=principals_sql(cfg.tenant_principals),
    )


def sql_hash(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def ensure_ops_tables(runner, cfg: Config) -> None:
    ops = cfg.ds("ops")
    runner.query(
        f"CREATE TABLE IF NOT EXISTS `{cfg.project}.{ops}.publish_log` "
        "(run_id STRING, invocation_id STRING, published_at TIMESTAMP, tables ARRAY<STRING>)"
    )
    runner.query(
        f"CREATE TABLE IF NOT EXISTS `{cfg.project}.{ops}.publish_policy_state` "
        "(policy STRING, table_name STRING, sql_hash STRING, applied_at TIMESTAMP)"
    )


def apply_policies(runner, cfg: Config, tables: list[Table], policies: list[Policy]) -> None:
    """Create or update the row policies. An unchanged policy is left alone.

    CREATE ... IF NOT EXISTS does not change an existing policy, so each policy's SQL is hashed
    in ops.publish_policy_state. A changed or never-recorded hash runs CREATE OR REPLACE.
    """
    tenant_tables = [t for t in tables if t.tenant_scoped]
    if not tenant_tables:
        return
    if not policies:
        if cfg.require_policies:
            raise PublishError(
                "tenant-scoped tables exist but orchestration/publish/policies/ has no policy SQL (D4)"
            )
        log("NO_POLICIES", "WARNING")
        return
    if not cfg.all_rows_principals or not cfg.tenant_principals:
        raise PublishError(
            "config needs all_rows_principals and tenant_principals: a principal named in no "
            "policy sees zero rows"
        )
    ops = cfg.ds("ops")
    state = {
        (r["policy"], r["table_name"]): r["sql_hash"]
        for r in runner.query(f"SELECT policy, table_name, sql_hash FROM `{cfg.project}.{ops}.publish_policy_state`")
    }
    for t in tenant_tables:
        for p in policies:
            sql = policy_sql(cfg, p, t.name)
            digest = sql_hash(sql)
            if state.get((p.name, t.name)) == digest:
                continue
            replace_sql = re.sub(
                r"CREATE\s+(?:OR\s+REPLACE\s+)?ROW ACCESS POLICY(\s+IF NOT EXISTS)?",
                "CREATE OR REPLACE ROW ACCESS POLICY",
                sql,
                count=1,
                flags=re.IGNORECASE,
            )
            runner.query(replace_sql)
            runner.query(
                f"MERGE `{cfg.project}.{ops}.publish_policy_state` T "
                "USING (SELECT @policy AS policy, @tbl AS table_name, @h AS sql_hash) S "
                "ON T.policy = S.policy AND T.table_name = S.table_name "
                "WHEN MATCHED THEN UPDATE SET sql_hash = S.sql_hash, applied_at = CURRENT_TIMESTAMP() "
                "WHEN NOT MATCHED THEN INSERT (policy, table_name, sql_hash, applied_at) "
                "VALUES (S.policy, S.table_name, S.sql_hash, CURRENT_TIMESTAMP())",
                {"policy": ("STRING", p.name), "tbl": ("STRING", t.name), "h": ("STRING", digest)},
            )
            log("POLICY_APPLIED", policy=p.name, table=t.name)


def apply_objects(runner, cfg: Config, objects: list[str], base: Path) -> None:
    for rel in objects:
        sql = render((base / rel).read_text(encoding="utf-8"), project=cfg.project, env=cfg.env)
        runner.query(sql)
        log("OBJECT_APPLIED", object=rel)


def build_transaction_sql(cfg: Config, plans: list[TablePlan]) -> tuple[str, dict]:
    """The generated script, with explicit column lists, and its query parameters."""
    stmts, params, published = [], {}, []
    for p in plans:
        t = p.table
        wh = ref(cfg.project, cfg.ds(t.dataset), t.name)
        bd = ref(cfg.project, cfg.ds("build"), t.name)
        cols = ", ".join(f"`{c}`" for c, _ in p.columns)
        if t.is_fact:
            if not p.dates:
                continue
            pname = f"{t.name}_dates"
            params[pname] = (p.date_type, p.dates)
            flt = f"{t.partition_column} IN UNNEST(@{pname})"
            stmts.append(f"DELETE FROM {wh} WHERE {flt};")
            stmts.append(f"INSERT INTO {wh} ({cols}) SELECT {cols} FROM {bd} WHERE {flt};")
        else:
            stmts.append(f"DELETE FROM {wh} WHERE TRUE;")
            stmts.append(f"INSERT INTO {wh} ({cols}) SELECT {cols} FROM {bd};")
        published.append(t.name)
    params["table_list"] = ("STRING", published)
    body = "\n    ".join(stmts)
    log_sql = (
        f"INSERT INTO `{cfg.project}.{cfg.ds('ops')}.publish_log` "
        "(run_id, invocation_id, published_at, tables) "
        "VALUES (@run_id, @invocation_id, CURRENT_TIMESTAMP(), @table_list);"
    )
    script = (
        "BEGIN\n"
        "  BEGIN TRANSACTION;\n"
        f"    {body}\n"
        f"    {log_sql}\n"
        "  COMMIT TRANSACTION;\n"
        "EXCEPTION WHEN ERROR THEN\n"
        "  ROLLBACK TRANSACTION;\n"
        "  RAISE USING MESSAGE = @@error.message;\n"
        "END;"
    )
    return script, params


def policy_names_present(runner, cfg: Config, layer: str) -> set[tuple[str, str]]:
    rows = runner.query(
        f"SELECT table_name, policy_name FROM `{cfg.project}.{cfg.ds(layer)}`.INFORMATION_SCHEMA.ROW_ACCESS_POLICIES"
    )
    return {(r["table_name"], r["policy_name"]) for r in rows}


def run_checks(runner, cfg: Config, plans: list[TablePlan], policies: list[Policy]) -> None:
    errors = []
    for p in plans:
        t = p.table
        if not p.publishes:
            continue
        wh = ref(cfg.project, cfg.ds(t.dataset), t.name)
        bd = ref(cfg.project, cfg.ds("build"), t.name)
        if t.is_fact:
            # Per changed date, so an extra row on one date cannot hide behind a missing row on another.
            col = t.partition_column
            params = {"d": (p.date_type, p.dates)}

            def per_date(table):
                sql = (
                    f"SELECT {col} AS p, COUNT(*) AS n FROM {table} "
                    f"WHERE {col} IN UNNEST(@d) GROUP BY p"
                )
                return {r["p"]: r["n"] for r in runner.query(sql, params)}

            wh_counts, build_counts = per_date(wh), per_date(bd)
            for d in p.dates:
                w, b = wh_counts.get(d, 0), build_counts.get(d, 0)
                if w != b:
                    errors.append(f"{t.name} {d}: wh has {w} rows, build has {b}")
            continue
        flt, params = "", None
        row = runner.query(
            f"SELECT (SELECT COUNT(*) FROM {wh}{flt}) AS wh_n, (SELECT COUNT(*) FROM {bd}{flt}) AS build_n",
            params,
        )[0]
        if row["wh_n"] != row["build_n"]:
            errors.append(f"{t.name}: wh has {row['wh_n']} rows, build has {row['build_n']}")

    tenant = [p.table for p in plans if p.table.tenant_scoped]
    if tenant and policies:
        present = policy_names_present(runner, cfg, "wh")
        for t in tenant:
            for pol in policies:
                if (t.name, pol.name) not in present:
                    errors.append(f"{t.name}: row policy {pol.name} is missing")
    if errors:
        raise PublishError("post-publish checks failed: " + "; ".join(errors))


# ------------------------------------------------------------------------------ the publish
def publish(
    runner,
    cfg: Config,
    tables: list[Table],
    objects: list[str],
    policies: list[Policy],
    *,
    dbt_exit_code: int,
    invocation_id: str | None,
    run_id: str,
    publish_all: bool = False,
    objects_dir: Path = HERE,
    dry_run: bool = False,
) -> str:
    # Step 1: the gate
    if dbt_exit_code != 0:
        log("PUBLISH_SKIPPED", "WARNING", dbt_exit_code=dbt_exit_code, run_id=run_id)
        return "skipped"

    # Step 2: what changed (read-only)
    plans = []
    for t in tables:
        build_cols = get_columns(runner, cfg, "build", t.name)
        if not build_cols:
            raise PublishError(f"{t.name}: not found in {cfg.ds('build')}")
        plan = TablePlan(t, build_cols)
        if t.is_fact:
            types = dict(build_cols)
            if t.partition_column not in types:
                raise PublishError(f"{t.name}: partition column {t.partition_column} is not in build")
            plan.date_type = types[t.partition_column]
            plan.dates = changed_partitions(runner, cfg, t, plan.date_type, invocation_id, publish_all)
        plans.append(plan)
        log("PLANNED", table=t.name, partitions=len(plan.dates) if t.is_fact else None)

    # Step 3: set-up, outside the transaction
    if dry_run:
        script, params = build_transaction_sql(cfg, plans)
        print(script)
        return "dry-run"
    ensure_ops_tables(runner, cfg)
    for plan in plans:
        t = plan.table
        wh = ref(cfg.project, cfg.ds(t.dataset), t.name)
        bd = ref(cfg.project, cfg.ds("build"), t.name)
        runner.query(f"CREATE TABLE IF NOT EXISTS {wh} LIKE {bd}")
        if t.is_fact:
            runner.query(f"ALTER TABLE {wh} SET OPTIONS (require_partition_filter = TRUE)")
        added = check_schema(plan.columns, get_columns(runner, cfg, t.dataset, t.name), t.name)
        types = dict(plan.columns)
        for col in added:
            runner.query(f"ALTER TABLE {wh} ADD COLUMN IF NOT EXISTS `{col}` {types[col]}")
            log("COLUMN_ADDED", table=t.name, column=col)
    apply_policies(runner, cfg, tables, policies)
    apply_objects(runner, cfg, objects, objects_dir)

    # Step 4: one transaction
    script, params = build_transaction_sql(cfg, plans)
    params["run_id"] = ("STRING", run_id)
    params["invocation_id"] = ("STRING", invocation_id or "all")
    runner.query(script, params)
    log("PUBLISHED", run_id=run_id, tables=params["table_list"][1])

    # Step 5: checks
    run_checks(runner, cfg, plans, policies)
    log("CHECKS_PASSED", run_id=run_id)
    return "published"


# ------------------------------------------------------------------------------ command line
def read_invocation_id(run_results: Path) -> str | None:
    try:
        return json.loads(run_results.read_text(encoding="utf-8"))["metadata"]["invocation_id"]
    except (OSError, KeyError, ValueError):
        return None


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", default=os.environ.get("DBT_TARGET"), help="dev or int (default: $DBT_TARGET)")
    ap.add_argument("--config", type=Path, help="default: config.<env>.yaml next to this script")
    ap.add_argument("--tables", type=Path, default=HERE / "tables.yaml")
    ap.add_argument("--policies-dir", type=Path, default=HERE / "policies")
    ap.add_argument("--dbt-exit-code", type=int, default=0, help="exit code of the dbt build that came first")
    ap.add_argument("--invocation-id", help="default: read from --run-results")
    ap.add_argument("--run-results", type=Path, default=Path("target/run_results.json"))
    ap.add_argument("--run-id", default=os.environ.get("CLOUD_RUN_EXECUTION") or str(uuid.uuid4()))
    ap.add_argument("--all", action="store_true", dest="publish_all", help="publish every partition (full load)")
    ap.add_argument("--dry-run", action="store_true", help="print the transaction and stop")
    return ap.parse_args(argv)


def main(argv=None, runner=None) -> int:
    args = parse_args(argv)
    try:
        if not args.env:
            raise PublishError("--env or $DBT_TARGET is required")
        cfg = load_config(args.config or HERE / f"config.{args.env}.yaml")
        if cfg.env != args.env:
            raise PublishError(f"config environment {cfg.env!r} does not match --env {args.env!r}")
        tables, objects = load_tables(args.tables)
        policies = load_policies(args.policies_dir) if args.policies_dir.is_dir() else []
        invocation_id = args.invocation_id or read_invocation_id(args.run_results)
        if args.dbt_exit_code == 0 and not args.publish_all and not invocation_id:
            raise PublishError("no invocation id: pass --invocation-id, or run after dbt so run_results.json exists")
        publish(
            runner or BigQueryRunner(cfg.project),
            cfg,
            tables,
            objects,
            policies,
            dbt_exit_code=args.dbt_exit_code,
            invocation_id=invocation_id,
            run_id=args.run_id,
            publish_all=args.publish_all,
            dry_run=args.dry_run,
        )
        return 0
    except PublishError as e:
        log("PUBLISH_FAILED", "ERROR", message=str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
