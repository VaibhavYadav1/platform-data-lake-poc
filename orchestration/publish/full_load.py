#!/usr/bin/env python3
"""E6: the daily full load.

A nightly full rebuild that checks the incremental logic has not drifted. Started by
`entrypoint.sh fullload`, which the poc-full-load-<env> workflow starts as the Cloud Run job
poc-dbt-runner-<env> with the argument `fullload`.

Steps, in this order:
  1. Clone every incremental fact:  ops_<env>.prev_<fact>  =  CLONE of build_<env>.<fact>.
  2. dbt build --full-refresh.      build_<env> now holds the from-scratch result.
  3. DQ39: compare each fact with its clone, both ways, and write the counts to
     ops_<env>.dq_result. A difference means the incremental logic missed something.
  4. DQ41: scan every STRING column of build_<env> for email-like values. A hit stops the run
     BEFORE publishing, so personal data never reaches wh (write-audit-publish).
  5. publish.py --all: publish every partition of the full build.

Exit codes: 0 all good; 1 a step failed (nothing published if it was before step 5); 3 the load
and the publish finished but DQ39 found drift, which is an error to explain (raise it with Dev 3).
The workflow fails on any non-zero exit, so the "failed poc-* workflow" alert fires.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import publish  # noqa: E402  (BigQueryRunner, shared with publish.py)

# DQ41: email-like values. RE2 syntax, so BigQuery accepts the same pattern.
EMAIL_PATTERN = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
EMAIL_RE = re.compile(EMAIL_PATTERN)

# Differ on every build by design, so they are left out of DQ39.
LINEAGE_COLUMNS = ("_dbt_loaded_at", "_dbt_invocation_id")

EXIT_FAILED = 1
EXIT_DRIFT = 3


class FullLoadError(Exception):
    """A step failed. The message says which; `code` is the exit code."""

    def __init__(self, message: str, code: int = EXIT_FAILED):
        super().__init__(message)
        self.code = code


def log(severity: str, event: str, **fields) -> None:
    print(json.dumps({"severity": severity, "event": event, **fields}, default=str), flush=True)


def run_command(cmd: list[str], description: str) -> None:
    log("INFO", "run_command", description=description, cmd=" ".join(cmd))
    code = subprocess.run(cmd).returncode
    if code != 0:
        raise FullLoadError(f"{description} exited {code}", code)


def load_facts(tables_path: Path = HERE / "tables.yaml") -> list[str]:
    tables, _objects = publish.load_tables(tables_path)
    return [t.name for t in tables if t.is_fact]


def ensure_ops_tables(runner, project: str, env: str, sql_path: Path = HERE / "ops_tables.sql") -> None:
    """Create ops_<env>.dq_result if missing. The file holds only CREATE TABLE IF NOT EXISTS."""
    text = sql_path.read_text(encoding="utf-8").replace("{project}", project).replace("{env}", env)
    for statement in text.split(";"):
        if "CREATE" in statement.upper():
            runner.query(statement)


# ---------------------------------------------------------------------------------- 1. clone
def clone_facts(runner, project: str, env: str, facts: list[str]) -> None:
    for fact in facts:
        # A clone is a metadata copy: fast, and it costs nothing until either table changes.
        runner.query(
            f"CREATE OR REPLACE TABLE `{project}.ops_{env}.prev_{fact}` "
            f"CLONE `{project}.build_{env}.{fact}`"
        )
        log("INFO", "cloned_fact", fact=fact)


# ----------------------------------------------------------------------- 2. dbt full refresh
def dbt_full_refresh(env: str) -> None:
    run_command(["dbt", "build", "--full-refresh", "--target", env], "dbt build --full-refresh")


# -------------------------------------------------------------------------------- 3. DQ39
def dq39_sql(project: str, env: str, fact: str) -> str:
    """Rows in the clone but not in the rebuild, and the other way round."""
    lineage = ", ".join(LINEAGE_COLUMNS)
    return f"""
WITH incremental AS (
  SELECT * EXCEPT ({lineage}) FROM `{project}.ops_{env}.prev_{fact}`
),
full_build AS (
  SELECT * EXCEPT ({lineage}) FROM `{project}.build_{env}.{fact}`
)
SELECT
  (SELECT COUNT(*) FROM (SELECT * FROM incremental EXCEPT DISTINCT SELECT * FROM full_build)) AS incremental_only,
  (SELECT COUNT(*) FROM (SELECT * FROM full_build EXCEPT DISTINCT SELECT * FROM incremental)) AS full_refresh_only
""".strip()


def compare_facts(runner, project: str, env: str, facts: list[str], run_id: str, git_sha: str) -> int:
    """Write one dq_result row per fact; return the total number of differing rows."""
    total = 0
    for fact in facts:
        row = runner.query(dq39_sql(project, env, fact))[0]
        incremental_only, full_refresh_only = int(row["incremental_only"]), int(row["full_refresh_only"])
        diff = incremental_only + full_refresh_only
        runner.query(
            f"INSERT INTO `{project}.ops_{env}.dq_result` "
            "(run_id, check_id, entity, incremental_only, full_refresh_only, total_diff, checked_at, git_sha) "
            "VALUES (@run_id, 'DQ39', @fact, @incremental_only, @full_refresh_only, @total_diff, "
            "CURRENT_TIMESTAMP(), @git_sha)",
            {
                "run_id": ("STRING", run_id),
                "fact": ("STRING", fact),
                "incremental_only": ("INT64", incremental_only),
                "full_refresh_only": ("INT64", full_refresh_only),
                "total_diff": ("INT64", diff),
                "git_sha": ("STRING", git_sha),
            },
        )
        if diff:
            total += diff
            log("ERROR", "dq39_drift_detected", fact=fact, incremental_only=incremental_only,
                full_refresh_only=full_refresh_only)
        else:
            log("INFO", "dq39_ok", fact=fact)
    return total


# -------------------------------------------------------------------------------- 4. DQ41
def string_columns(runner, project: str, env: str) -> dict[str, list[str]]:
    rows = runner.query(
        f"SELECT table_name, column_name FROM `{project}.build_{env}`.INFORMATION_SCHEMA.COLUMNS "
        "WHERE data_type = 'STRING' ORDER BY table_name, ordinal_position"
    )
    tables: dict[str, list[str]] = {}
    for r in rows:
        tables.setdefault(r["table_name"], []).append(r["column_name"])
    return tables


def scan_personal_data(runner, project: str, env: str) -> list[dict]:
    """Every STRING column of build, for email-like values. One scan per table."""
    violations = []
    for table, columns in string_columns(runner, project, env).items():
        counts = ", ".join(
            f"COUNTIF(REGEXP_CONTAINS(`{c}`, @pattern)) AS m{i}" for i, c in enumerate(columns)
        )
        row = runner.query(
            f"SELECT {counts} FROM `{project}.build_{env}.{table}`",
            {"pattern": ("STRING", EMAIL_PATTERN)},
        )[0]
        for i, column in enumerate(columns):
            if row[f"m{i}"]:
                violations.append({"table": table, "column": column, "matches": int(row[f"m{i}"])})
    return violations


# --------------------------------------------------------------------------------- 5. publish
def publish_all(env: str) -> None:
    run_command(
        [sys.executable, str(HERE / "publish.py"), "--all", "--env", env],
        "publish.py --all",
    )


# ------------------------------------------------------------------------------------- run
def run_full_load(runner, project: str, env: str, run_id: str, facts: list[str], git_sha: str = "unknown") -> int:
    ensure_ops_tables(runner, project, env)

    clone_facts(runner, project, env, facts)  # 1
    dbt_full_refresh(env)  # 2
    drift = compare_facts(runner, project, env, facts, run_id, git_sha)  # 3

    violations = scan_personal_data(runner, project, env)  # 4, before anything is published
    if violations:
        log("ERROR", "dq41_personal_data_found", violations=violations)
        raise FullLoadError(f"DQ41: email-like values in build ({len(violations)} columns); nothing published")

    publish_all(env)  # 5

    if drift:
        log("ERROR", "dq39_drift", total_diff=drift,
            message="the incremental logic missed rows; the full rebuild was published. Raise it with Dev 3")
        return EXIT_DRIFT
    log("INFO", "full_load_complete", run_id=run_id)
    return 0


def main() -> int:
    env = os.environ.get("DBT_TARGET", "dev")
    project = os.environ.get("GCP_PROJECT") or os.environ.get("POC_PROJECT") or ""
    # The workflow passes its execution id, so dq_result and full_load_log carry the same run_id.
    run_id = os.environ.get("RUN_ID") or str(uuid.uuid4())
    log("INFO", "full_load_start", env=env, project=project, run_id=run_id)
    try:
        if not project:
            raise FullLoadError("set GCP_PROJECT (or POC_PROJECT)")
        facts = load_facts()
        return run_full_load(
            publish.BigQueryRunner(project), project, env, run_id, facts, os.environ.get("GIT_SHA", "unknown")
        )
    except (FullLoadError, publish.PublishError) as e:
        log("ERROR", "full_load_failed", message=str(e))
        return getattr(e, "code", EXIT_FAILED)


if __name__ == "__main__":
    sys.exit(main())
