"""Tests for full_load.py: the order of the five steps, DQ39, DQ41 and what each failure does.

No BigQuery, dbt or subprocess: FakeRunner records every statement and answers the read queries,
and run_command is replaced by a recorder, so the tests see the exact sequence of work.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import full_load as fl  # noqa: E402


class FakeRunner:
    def __init__(self, drift=None, string_columns=None, email_hits=None, events=None):
        self.drift = drift or {}  # fact -> (incremental_only, full_refresh_only)
        self.string_columns = string_columns if string_columns is not None else [
            {"table_name": "dim_store", "column_name": "store_name"},
            {"table_name": "dim_store", "column_name": "store_id"},
            {"table_name": "fct_alert", "column_name": "alert_id"},
        ]
        self.email_hits = email_hits or {}  # (table, index) -> matches
        self.events = events if events is not None else []
        self.calls = []

    @property
    def sqls(self):
        return [c[0] for c in self.calls]

    def query(self, sql, params=None):
        self.calls.append((sql, params))
        s = sql.lstrip()
        if "INFORMATION_SCHEMA.COLUMNS" in s:
            self.events.append("list_string_columns")
            return self.string_columns
        if s.startswith("CREATE OR REPLACE TABLE"):
            self.events.append("clone:" + s.split("prev_")[1].split("`")[0])
            return []
        if s.startswith("WITH incremental"):
            fact = s.split("prev_")[1].split("`")[0]
            self.events.append("dq39:" + fact)
            a, b = self.drift.get(fact, (0, 0))
            return [{"incremental_only": a, "full_refresh_only": b}]
        if s.startswith("SELECT COUNTIF"):
            table = s.split("build_dev.")[1].split("`")[0]
            self.events.append("scan:" + table)
            n = sum(1 for c in self.string_columns if c["table_name"] == table)
            return [{f"m{i}": self.email_hits.get((table, i), 0) for i in range(n)}]
        return []


@pytest.fixture
def commands(monkeypatch):
    """Replace run_command; record the commands, and let a test make one of them fail."""
    ran = {"cmds": [], "fail": None, "events": None}

    def fake(cmd, description):
        ran["cmds"].append(cmd)
        if ran["events"] is not None:
            ran["events"].append("cmd:" + description)
        if ran["fail"] == description:
            raise fl.FullLoadError(f"{description} exited 7", 7)

    monkeypatch.setattr(fl, "run_command", fake)
    return ran


FACTS = ["fct_alert", "fct_alert_history", "fct_work_order", "fct_case", "fct_wheel_event"]


def go(runner, commands, facts=FACTS):
    return fl.run_full_load(runner, "proj", "dev", "run-1", facts, "sha1")


# ------------------------------------------------------------------------------ the sequence
def test_the_steps_run_in_the_plans_order(commands):
    events = []
    # Use only two facts so the assertion stays concise
    facts = ["fct_alert", "fct_alert_history"]
    r = FakeRunner(events=events)
    commands["events"] = events
    assert fl.run_full_load(r, "proj", "dev", "run-1", facts, "sha1") == 0
    order = [e for e in events if e != "list_string_columns"]
    assert order == [
        "clone:fct_alert",
        "clone:fct_alert_history",
        "cmd:dbt build --full-refresh",
        "dq39:fct_alert",
        "dq39:fct_alert_history",
        "scan:dim_store",
        "scan:fct_alert",
        "cmd:publish.py --all",
    ]


def test_it_runs_dbt_full_refresh_and_publish_all(commands):
    go(FakeRunner(), commands)
    dbt, publish_cmd = commands["cmds"]
    assert dbt == ["dbt", "build", "--full-refresh", "--target", "dev"]
    assert publish_cmd[1].endswith("publish.py") and publish_cmd[2:] == ["--all", "--env", "dev"]


def test_facts_come_from_tables_yaml():
    assert fl.load_facts() == FACTS


def test_dq39_table_is_created_before_anything_is_written():
    r = FakeRunner()
    fl.ensure_ops_tables(r, "proj", "dev")
    assert len(r.sqls) == 1 and r.sqls[0].lstrip().startswith("-- E6")
    assert "CREATE TABLE IF NOT EXISTS `proj.ops_dev.dq_result`" in r.sqls[0]
    assert "{project}" not in r.sqls[0] and "{env}" not in r.sqls[0]


# ------------------------------------------------------------------------------------ clone
def test_each_fact_is_cloned_from_build_to_ops(commands):
    r = FakeRunner()
    go(r, commands)
    clones = [s for s in r.sqls if s.startswith("CREATE OR REPLACE TABLE")]
    assert clones[0] == "CREATE OR REPLACE TABLE `proj.ops_dev.prev_fct_alert` CLONE `proj.build_dev.fct_alert`"
    assert len(clones) == len(FACTS)


# -------------------------------------------------------------------------------------- DQ39
def test_dq39_compares_both_ways_without_the_lineage_columns():
    sql = fl.dq39_sql("proj", "dev", "fct_alert")
    assert "SELECT * FROM incremental EXCEPT DISTINCT SELECT * FROM full_build" in sql
    assert "SELECT * FROM full_build EXCEPT DISTINCT SELECT * FROM incremental" in sql
    assert sql.count("EXCEPT (_dbt_loaded_at, _dbt_invocation_id)") == 2
    # BigQuery refuses to mix EXCEPT and UNION in one unparenthesised query
    assert "UNION" not in sql


def test_no_drift_records_zero_rows_and_exits_0(commands):
    r = FakeRunner()
    assert go(r, commands) == 0
    inserts = [c for c in r.calls if c[0].lstrip().startswith("INSERT INTO `proj.ops_dev.dq_result`")]
    assert [c[1]["fact"][1] for c in inserts] == FACTS
    assert all(c[1]["total_diff"] == ("INT64", 0) for c in inserts)
    assert inserts[0][1]["run_id"] == ("STRING", "run-1")


def test_drift_is_recorded_published_and_then_fails_the_run(commands):
    r = FakeRunner(drift={"fct_alert": (3, 2)})
    assert go(r, commands) == fl.EXIT_DRIFT
    insert = next(c for c in r.calls if c[1] and c[1].get("fact") == ("STRING", "fct_alert"))
    assert insert[1]["incremental_only"] == ("INT64", 3)
    assert insert[1]["full_refresh_only"] == ("INT64", 2)
    assert insert[1]["total_diff"] == ("INT64", 5)
    # the full rebuild is the correct one, so it is still published; the run fails afterwards
    assert commands["cmds"][-1][-3:] == ["--all", "--env", "dev"]


# -------------------------------------------------------------------------------------- DQ41
def test_every_string_column_is_scanned_including_name_columns():
    r = FakeRunner()
    fl.scan_personal_data(r, "proj", "dev")
    store_scan = next(s for s in r.sqls if "dim_store" in s and s.startswith("SELECT COUNTIF"))
    assert "`store_name`" in store_scan and "`store_id`" in store_scan
    assert "NOT IN" not in store_scan


def test_the_pattern_is_a_query_parameter():
    r = FakeRunner()
    fl.scan_personal_data(r, "proj", "dev")
    scan = next(c for c in r.calls if c[0].startswith("SELECT COUNTIF"))
    assert "@pattern" in scan[0] and scan[1] == {"pattern": ("STRING", fl.EMAIL_PATTERN)}


def test_an_email_like_value_stops_the_run_before_publishing(commands):
    r = FakeRunner(email_hits={("dim_store", 0): 4})
    with pytest.raises(fl.FullLoadError, match="DQ41"):
        go(r, commands)
    assert not any("publish.py" in " ".join(c) for c in commands["cmds"])


def test_violation_names_table_and_column():
    r = FakeRunner(email_hits={("dim_store", 1): 2})
    assert fl.scan_personal_data(r, "proj", "dev") == [{"table": "dim_store", "column": "store_id", "matches": 2}]


@pytest.mark.parametrize("text", ["user@example.com", "first.last@company.co.uk", "test+tag@domain.org"])
def test_email_pattern_matches_emails(text):
    assert fl.EMAIL_RE.search(text)


@pytest.mark.parametrize("text", ["not an email", "store-123", "@nodomain", "incomplete@"])
def test_email_pattern_ignores_other_text(text):
    assert not fl.EMAIL_RE.search(text)


# -------------------------------------------------------------------------------- failures
def test_a_failed_dbt_build_stops_everything_after_it(commands):
    commands["fail"] = "dbt build --full-refresh"
    r = FakeRunner()
    with pytest.raises(fl.FullLoadError):
        go(r, commands)
    assert not any(s.startswith("WITH incremental") for s in r.sqls)
    assert len(commands["cmds"]) == 1  # publish never ran


def test_a_failed_publish_fails_the_run(commands):
    commands["fail"] = "publish.py --all"
    with pytest.raises(fl.FullLoadError):
        go(FakeRunner(), commands)


# ------------------------------------------------------------------------------------ main
def test_main_needs_a_project(monkeypatch):
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    monkeypatch.delenv("POC_PROJECT", raising=False)
    assert fl.main() == 1


def test_main_returns_the_drift_code_and_uses_the_workflows_run_id(monkeypatch, commands):
    r = FakeRunner(drift={"fct_alert": (1, 0)})
    monkeypatch.setenv("GCP_PROJECT", "proj")
    monkeypatch.setenv("DBT_TARGET", "dev")
    monkeypatch.setenv("RUN_ID", "workflow-exec-42")
    monkeypatch.setattr(fl.publish, "BigQueryRunner", lambda project: r)
    assert fl.main() == fl.EXIT_DRIFT
    insert = next(c for c in r.calls if c[1] and "run_id" in c[1])
    assert insert[1]["run_id"] == ("STRING", "workflow-exec-42")
