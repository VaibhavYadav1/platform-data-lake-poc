"""E11 evidence tool: fingerprints, comparison and the command line, against a fake BigQuery."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wh_fingerprint as w  # noqa: E402

p = w.publish
CFG = p.Config(project="proj", env="dev")
FACT = p.Table("fct_alert", "fact", "wh", "alert_date", True)
DIM = p.Table("dim_store", "dim", "wh", None, True)
SEC = p.Table("map_tenant_access", "dim", "sec", None, False)
TABLES = [FACT, DIM, SEC]


class FakeRunner:
    """tables: dataset -> {table: (fingerprint, rows)}. policies: set of (table, policy)."""

    def __init__(self, tables=None, policies=None):
        self.tables = tables if tables is not None else {
            "wh_dev": {"fct_alert": (111, 10), "dim_store": (222, 5), "mv_cart": (None, 0)},
            "sec_dev": {"map_tenant_access": (333, 3)},
        }
        self.policies = policies if policies is not None else {("fct_alert", "rls_tenant"), ("dim_store", "rls_tenant")}
        self.sqls = []

    def query(self, sql, params=None):
        self.sqls.append(sql)
        if "INFORMATION_SCHEMA.TABLES" in sql:
            dataset = sql.split("`.INFORMATION_SCHEMA")[0].split(".")[-1]
            return [{"table_name": t} for t in sorted(self.tables[dataset])]
        if "ROW_ACCESS_POLICIES" in sql:
            return [{"table_name": t, "policy_name": n} for t, n in self.policies]
        if sql.startswith("SELECT BIT_XOR"):
            dataset, table = sql.split("FROM `proj.")[1].split("`")[0].split(".")
            fp, n = self.tables[dataset][table]
            return [{"fingerprint": fp, "n": n}]
        raise AssertionError(sql)


def snap(runner=None, at="t"):
    return w.snapshot(runner or FakeRunner(), CFG, TABLES, taken_at=at)


# -------------------------------------------------------------------------------- the snapshot
def test_every_table_in_wh_and_sec_is_fingerprinted():
    s = snap()
    assert s["tables"] == {
        "wh_dev.dim_store": {"fingerprint": 222, "rows": 5},
        "wh_dev.fct_alert": {"fingerprint": 111, "rows": 10},
        "wh_dev.mv_cart": {"fingerprint": None, "rows": 0},  # empty: BIT_XOR is NULL
        "sec_dev.map_tenant_access": {"fingerprint": 333, "rows": 3},
    }


def test_the_fingerprint_query_is_the_plans():
    sql = w.fingerprint_sql("proj", "wh_dev", "dim_store", None)
    assert sql.startswith("SELECT BIT_XOR(FARM_FINGERPRINT(TO_JSON_STRING(t)))")
    assert "FROM `proj.wh_dev.dim_store` AS t" in sql and "WHERE" not in sql


def test_facts_get_a_partition_filter_covering_every_date():
    """wh facts require a partition filter, and a fingerprint must not skip any date."""
    r = FakeRunner()
    snap(r)
    fact_sql = next(s for s in r.sqls if "fct_alert" in s and s.startswith("SELECT BIT_XOR"))
    assert "WHERE alert_date >= DATE '1900-01-01'" in fact_sql
    dim_sql = next(s for s in r.sqls if "dim_store" in s and s.startswith("SELECT BIT_XOR"))
    assert "WHERE" not in dim_sql


def test_row_policies_are_recorded():
    assert snap()["policies"] == ["dim_store:rls_tenant", "fct_alert:rls_tenant"]


# -------------------------------------------------------------------------------- the comparison
def test_an_untouched_wh_passes():
    report = w.compare(snap(at="before"), snap(at="after"))
    assert w.passed(report)


def test_a_changed_table_fails_and_is_named():
    r = FakeRunner()
    before = snap(r)
    r.tables["wh_dev"]["fct_alert"] = (999, 11)
    report = w.compare(before, snap(r))
    assert report["changed"] == ["wh_dev.fct_alert"] and not w.passed(report)


def test_same_row_count_but_different_content_is_still_a_change():
    r = FakeRunner()
    before = snap(r)
    r.tables["wh_dev"]["dim_store"] = (223, 5)
    assert w.compare(before, snap(r))["changed"] == ["wh_dev.dim_store"]


def test_a_new_or_missing_table_fails():
    r = FakeRunner()
    before = snap(r)
    del r.tables["wh_dev"]["mv_cart"]
    r.tables["wh_dev"]["fct_new"] = (1, 1)
    report = w.compare(before, snap(r))
    assert report["removed"] == ["wh_dev.mv_cart"] and report["added"] == ["wh_dev.fct_new"]
    assert not w.passed(report)


def test_a_lost_row_policy_fails():
    r = FakeRunner()
    before = snap(r)
    r.policies = {("fct_alert", "rls_tenant")}
    report = w.compare(before, snap(r))
    assert report["policies_lost"] == ["dim_store:rls_tenant"] and not w.passed(report)


def test_a_policy_missing_from_a_tenant_table_fails_even_if_it_was_never_there():
    pols = [p.Policy("rls_all_rows", "x"), p.Policy("rls_tenant", "x")]
    expected = w.expected_policies(TABLES, pols)
    assert expected == ["dim_store:rls_all_rows", "dim_store:rls_tenant",
                        "fct_alert:rls_all_rows", "fct_alert:rls_tenant"]
    report = w.compare(snap(), snap(), expected)
    assert report["policies_missing"] == ["dim_store:rls_all_rows", "fct_alert:rls_all_rows"]


def test_the_report_says_pass_or_fail():
    before, r = snap(at="b"), FakeRunner()
    ok = w.render(before, snap(r, at="a"), w.compare(before, snap(r, at="a")))
    assert "RESULT: PASS" in ok and "CHANGED" not in ok
    r.tables["wh_dev"]["fct_alert"] = (0, 0)
    after = snap(r, at="a")
    bad = w.render(before, after, w.compare(before, after))
    assert "RESULT: FAIL" in bad and "CHANGED  wh_dev.fct_alert" in bad


# ---------------------------------------------------------------------------------- the command
def test_snapshot_then_compare_through_the_command_line(tmp_path):
    cfg = tmp_path / "config.dev.yaml"
    cfg.write_text("project: proj\nenvironment: dev\n")
    tables = tmp_path / "tables.yaml"
    tables.write_text("tables:\n  - {name: fct_alert, kind: fact, partition_column: alert_date}\n"
                      "  - {name: dim_store, kind: dim}\n")
    before = tmp_path / "evidence" / "before.json"
    common = ["--env", "dev", "--config", str(cfg), "--tables", str(tables), "--policies-dir", str(tmp_path / "none")]

    assert w.main(["snapshot", *common, "--out", str(before)], runner=FakeRunner()) == 0
    assert json.loads(before.read_text())["tables"]["wh_dev.fct_alert"]["rows"] == 10

    assert w.main(["compare", *common, "--before", str(before)], runner=FakeRunner()) == 0
    changed = FakeRunner()
    changed.tables["wh_dev"]["dim_store"] = (1, 1)
    assert w.main(["compare", *common, "--before", str(before)], runner=changed) == 1


def test_compare_needs_a_before_file(tmp_path):
    cfg = tmp_path / "config.dev.yaml"
    cfg.write_text("project: proj\nenvironment: dev\n")
    tables = tmp_path / "t.yaml"
    tables.write_text("tables:\n  - {name: dim_store, kind: dim}\n")
    assert w.main(["compare", "--env", "dev", "--config", str(cfg), "--tables", str(tables)], runner=FakeRunner()) == 2


def test_env_must_match_the_config(tmp_path):
    cfg = tmp_path / "config.dev.yaml"
    cfg.write_text("project: proj\nenvironment: dev\n")
    assert w.main(["snapshot", "--env", "int", "--config", str(cfg)], runner=FakeRunner()) == 2
