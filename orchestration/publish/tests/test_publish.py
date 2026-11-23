"""Tests for publish.py: SQL generation, the skip path, the column-change stop, and the checks.

No BigQuery needed: FakeRunner records every statement and answers the few read queries.
"""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish as p  # noqa: E402

D1, D2 = dt.date(2026, 11, 19), dt.date(2026, 11, 20)

CFG = p.Config(
    project="proj",
    env="dev",
    all_rows_principals=("serviceAccount:w@proj.iam",),
    tenant_principals=("user:t@x.com",),
)

FACT = p.Table("fct_alert", "fact", "wh", "alert_date", True)
DIM = p.Table("dim_store", "dim", "wh", None, True)
OPEN_DIM = p.Table("dim_date", "dim", "wh", None, False)
SEC = p.Table("map_tenant_access", "security", "sec", None, False)

COLS = {
    "fct_alert": [("alert_id", "STRING"), ("alert_date", "DATE"), ("tenant_id", "STRING")],
    "dim_store": [("store_id", "STRING"), ("tenant_id", "STRING")],
    "dim_date": [("d", "DATE")],
    "map_tenant_access": [("principal", "STRING"), ("tenant_id", "STRING")],
}

POLICIES = [
    p.Policy(
        "rls_all_rows",
        "CREATE ROW ACCESS POLICY IF NOT EXISTS rls_all_rows ON `{project}.wh_{env}.{table}` "
        "GRANT TO ({all_rows_principals}) FILTER USING (TRUE);",
    ),
    p.Policy(
        "rls_tenant",
        "CREATE ROW ACCESS POLICY IF NOT EXISTS rls_tenant ON `{project}.wh_{env}.{table}` "
        "GRANT TO ({tenant_principals}) FILTER USING (tenant_id = 'x');",
    ),
]


class FakeRunner:
    def __init__(self, wh_cols=None, counts=None, state=None, policies_present=None, dates=None, fact_counts=None):
        self.calls = []
        self.fact_counts = fact_counts or {}
        self.wh_cols = wh_cols if wh_cols is not None else COLS
        self.counts = counts or {}
        self.state = state or []
        self.policies_present = policies_present
        self.dates = dates if dates is not None else [D1, D2]

    @property
    def sqls(self):
        return [c[0] for c in self.calls]

    def query(self, sql, params=None):
        self.calls.append((sql, params))
        if "INFORMATION_SCHEMA.COLUMNS" in sql:
            layer = sql.split("`.INFORMATION_SCHEMA")[0].split(".")[-1].split("_")[0]
            src = COLS if layer == "build" else self.wh_cols
            return [{"column_name": c, "data_type": t} for c, t in src.get(params["t"][1], [])]
        if "SELECT DISTINCT" in sql:
            return [{"p": d} for d in self.dates] + [{"p": None}]
        if "publish_policy_state`" in sql and sql.lstrip().startswith("SELECT"):
            return self.state
        if "ROW_ACCESS_POLICIES" in sql:
            present = self.policies_present
            if present is None:
                present = {(t.name, pol.name) for t in (FACT, DIM) for pol in POLICIES}
            return [{"table_name": t, "policy_name": n} for t, n in present]
        if " AS p, COUNT(*) AS n FROM " in sql:
            side = "build" if "build_" in sql.split(" FROM ")[1].split(" ")[0] else "wh"
            override = self.fact_counts.get(side)
            return override if override is not None else [{"p": d, "n": 5} for d in params["d"][1]]
        if sql.startswith("SELECT (SELECT COUNT"):
            return [self.counts.get(self._table(sql), {"wh_n": 5, "build_n": 5})]
        return []

    @staticmethod
    def _table(sql):
        for name in COLS:
            if f".{name}`" in sql:
                return name
        return None


def go(runner, tables=(FACT, DIM), policies=POLICIES, **kw):
    args = dict(dbt_exit_code=0, invocation_id="inv-1", run_id="run-1", objects_dir=Path("."))
    args.update(kw)
    return p.publish(runner, CFG, list(tables), [], policies, **args)


# ---------------------------------------------------------------------------------- skip path
def test_failed_dbt_publishes_nothing():
    r = FakeRunner()
    assert go(r, dbt_exit_code=1) == "skipped"
    assert r.calls == []  # wh and build were not even read


# ---------------------------------------------------------------------------- transaction SQL
def transaction(r):
    return next(s for s in r.sqls if s.startswith("BEGIN"))


def test_one_transaction_with_rollback_and_log():
    r = FakeRunner()
    assert go(r) == "published"
    sql = transaction(r)
    assert sql.count("BEGIN TRANSACTION") == 1
    assert sql.count("COMMIT TRANSACTION") == 1
    assert "ROLLBACK TRANSACTION" in sql and "RAISE USING MESSAGE = @@error.message" in sql
    assert "`proj.ops_dev.publish_log`" in sql
    # everything lands in a single query call
    assert sum(s.startswith("BEGIN") for s in r.sqls) == 1


def test_dimensions_are_replaced_whole_and_facts_by_changed_partition():
    r = FakeRunner()
    go(r)
    sql = transaction(r)
    assert "DELETE FROM `proj.wh_dev.dim_store` WHERE TRUE;" in sql
    assert "DELETE FROM `proj.wh_dev.fct_alert` WHERE alert_date IN UNNEST(@fct_alert_dates);" in sql
    assert "FROM `proj.build_dev.fct_alert` WHERE alert_date IN UNNEST(@fct_alert_dates);" in sql
    params = next(c[1] for c in r.calls if c[0].startswith("BEGIN"))
    assert params["fct_alert_dates"] == ("DATE", [D1, D2])
    assert params["table_list"] == ("STRING", ["fct_alert", "dim_store"])
    assert params["run_id"] == ("STRING", "run-1")


def test_column_lists_are_explicit():
    r = FakeRunner()
    go(r)
    assert "(`store_id`, `tenant_id`) SELECT `store_id`, `tenant_id` FROM `proj.build_dev.dim_store`" in transaction(r)


def test_fact_with_no_changed_partitions_is_left_alone():
    r = FakeRunner(dates=[])
    go(r)
    sql = transaction(r)
    assert "fct_alert" not in sql.replace("`proj.build_dev.fct_alert`", "")
    assert "dim_store" in sql


def test_security_table_goes_to_sec_dataset():
    r = FakeRunner()
    go(r, tables=(SEC,), policies=[])
    assert "DELETE FROM `proj.sec_dev.map_tenant_access` WHERE TRUE;" in transaction(r)


def test_publish_all_reads_every_partition_not_the_invocation():
    r = FakeRunner()
    go(r, publish_all=True)
    distinct = [c for c in r.calls if "SELECT DISTINCT" in c[0]][0]
    assert "_dbt_invocation_id" not in distinct[0] and distinct[1] is None


def test_incremental_publish_filters_on_the_invocation():
    r = FakeRunner()
    go(r)
    distinct = [c for c in r.calls if "SELECT DISTINCT" in c[0]][0]
    assert "_dbt_invocation_id = @invocation_id" in distinct[0]
    assert distinct[1] == {"invocation_id": ("STRING", "inv-1")}


def test_dry_run_changes_nothing():
    r = FakeRunner()
    assert go(r, dry_run=True) == "dry-run"
    assert not any(s.startswith(("CREATE", "ALTER", "BEGIN", "MERGE")) for s in r.sqls)


# ------------------------------------------------------------------------------------- set-up
def test_setup_runs_before_the_transaction_and_is_idempotent():
    r = FakeRunner()
    go(r)
    i_tx = next(i for i, s in enumerate(r.sqls) if s.startswith("BEGIN"))
    setup = r.sqls[:i_tx]
    assert "CREATE TABLE IF NOT EXISTS `proj.wh_dev.fct_alert` LIKE `proj.build_dev.fct_alert`" in setup
    assert "ALTER TABLE `proj.wh_dev.fct_alert` SET OPTIONS (require_partition_filter = TRUE)" in setup
    assert not any("require_partition_filter" in s and "dim_store" in s for s in r.sqls)
    # nothing in set-up recreates or drops a published table
    assert not any("OR REPLACE TABLE" in s or s.startswith("DROP") for s in r.sqls)


def test_new_column_is_added():
    wh = dict(COLS, dim_store=[("store_id", "STRING")])
    r = FakeRunner(wh_cols=wh)
    go(r, tables=(DIM,))
    assert "ALTER TABLE `proj.wh_dev.dim_store` ADD COLUMN IF NOT EXISTS `tenant_id` STRING" in r.sqls


def test_removed_column_stops_before_anything_is_published():
    wh = dict(COLS, dim_store=COLS["dim_store"] + [("old_col", "STRING")])
    r = FakeRunner(wh_cols=wh)
    with pytest.raises(p.PublishError, match=r"removed columns \['old_col'\]"):
        go(r, tables=(DIM,))
    assert not any(s.startswith("BEGIN") for s in r.sqls)


def test_retyped_column_stops_before_anything_is_published():
    wh = dict(COLS, dim_store=[("store_id", "INT64"), ("tenant_id", "STRING")])
    r = FakeRunner(wh_cols=wh)
    with pytest.raises(p.PublishError, match=r"store_id \(INT64 to STRING\)"):
        go(r, tables=(DIM,))
    assert not any(s.startswith("BEGIN") for s in r.sqls)


def test_missing_build_table_is_an_error():
    r = FakeRunner()
    ghost = p.Table("dim_ghost", "dim", "wh", None, False)
    with pytest.raises(p.PublishError, match="dim_ghost: not found in build_dev"):
        go(r, tables=(ghost,))


# ------------------------------------------------------------------------------------ policies
def test_policies_applied_to_tenant_tables_only_with_or_replace_on_first_run():
    r = FakeRunner()
    go(r, tables=(DIM, OPEN_DIM))
    created = [s for s in r.sqls if "ROW ACCESS POLICY" in s and s.startswith("CREATE")]
    assert len(created) == 2  # two policies on dim_store, none on dim_date
    assert all(s.startswith("CREATE OR REPLACE ROW ACCESS POLICY") for s in created)
    assert all("dim_store" in s and "dim_date" not in s for s in created)
    assert 'GRANT TO ("serviceAccount:w@proj.iam")' in created[0]
    assert 'GRANT TO ("user:t@x.com")' in created[1]


def test_unchanged_policy_is_not_reapplied():
    base = FakeRunner()
    go(base, tables=(DIM,))
    state = [
        {"policy": pol.name, "table_name": "dim_store", "sql_hash": p.sql_hash(p.policy_sql(CFG, pol, "dim_store"))}
        for pol in POLICIES
    ]
    r = FakeRunner(state=state)
    go(r, tables=(DIM,))
    assert not any(s.startswith("CREATE OR REPLACE ROW ACCESS POLICY") for s in r.sqls)


def test_changed_grantees_replace_the_policy():
    state = [
        {"policy": pol.name, "table_name": "dim_store", "sql_hash": "stale"} for pol in POLICIES
    ]
    r = FakeRunner(state=state)
    go(r, tables=(DIM,))
    assert sum(s.startswith("CREATE OR REPLACE ROW ACCESS POLICY") for s in r.sqls) == 2


def test_tenant_tables_without_policy_sql_fail_closed():
    with pytest.raises(p.PublishError, match="no policy SQL"):
        go(FakeRunner(), tables=(DIM,), policies=[])


def test_empty_tenant_principals_fail():
    cfg = p.Config("proj", "dev", all_rows_principals=("a",), tenant_principals=())
    with pytest.raises(p.PublishError, match="a principal named in no policy sees zero rows"):
        p.apply_policies(FakeRunner(), cfg, [DIM], POLICIES)


# -------------------------------------------------------------------------------------- checks
def test_row_count_mismatch_fails_the_publish():
    r = FakeRunner(counts={"dim_store": {"wh_n": 4, "build_n": 5}})
    with pytest.raises(p.PublishError, match="dim_store: wh has 4 rows, build has 5"):
        go(r)


def test_fact_counts_use_only_the_changed_partitions():
    r = FakeRunner()
    go(r)
    counts = [c for c in r.calls if " AS p, COUNT(*) AS n FROM " in c[0] and "fct_alert" in c[0]]
    assert len(counts) == 2  # one for wh, one for build
    for sql, params in counts:
        assert "WHERE alert_date IN UNNEST(@d) GROUP BY p" in sql
        assert params == {"d": ("DATE", [D1, D2])}


def test_fact_counts_are_compared_per_date_not_in_total():
    # Totals match (10 = 10) but the dates are off in opposite directions.
    r = FakeRunner(
        fact_counts={
            "wh": [{"p": D1, "n": 6}, {"p": D2, "n": 4}],
            "build": [{"p": D1, "n": 5}, {"p": D2, "n": 5}],
        }
    )
    with pytest.raises(p.PublishError) as e:
        go(r)
    msg = str(e.value)
    assert f"fct_alert {D1}: wh has 6 rows, build has 5" in msg
    assert f"fct_alert {D2}: wh has 4 rows, build has 5" in msg


def test_fact_date_missing_from_wh_counts_as_zero():
    r = FakeRunner(fact_counts={"wh": [{"p": D1, "n": 5}]})
    with pytest.raises(p.PublishError, match=f"fct_alert {D2}: wh has 0 rows, build has 5"):
        go(r)


def test_missing_row_policy_fails_the_publish():
    present = {("fct_alert", "rls_all_rows"), ("fct_alert", "rls_tenant"), ("dim_store", "rls_all_rows")}
    r = FakeRunner(policies_present=present)
    with pytest.raises(p.PublishError, match="dim_store: row policy rls_tenant is missing"):
        go(r)


# ------------------------------------------------------------------------------ configuration
def write(tmp_path, name, text):
    f = tmp_path / name
    f.write_text(text)
    return f


def test_load_tables_validates(tmp_path):
    f = write(tmp_path, "t.yaml", "tables:\n  - {name: fct_a, kind: fact}\n")
    with pytest.raises(p.PublishError, match="needs a partition_column"):
        p.load_tables(f)
    f = write(tmp_path, "t2.yaml", "tables:\n  - {name: x, kind: weird}\n")
    with pytest.raises(p.PublishError, match="bad table entry"):
        p.load_tables(f)


def test_load_tables_reads_plan_format(tmp_path):
    f = write(
        tmp_path,
        "t.yaml",
        "tables:\n"
        "  - {name: fct_alert, kind: fact, partition_column: alert_date, tenant_scoped: true}\n"
        "  - {name: map_tenant_access, kind: dim, tenant_scoped: false, dataset: sec}\n"
        "objects:\n  - objects/mv_a.sql\n",
    )
    tables, objects = p.load_tables(f)
    assert tables[0].is_fact and tables[0].tenant_scoped
    assert tables[1].dataset == "sec" and not tables[1].is_fact
    assert objects == ["objects/mv_a.sql"]


def test_main_skips_when_dbt_failed(tmp_path, capsys):
    cfg = write(tmp_path, "c.yaml", "project: proj\nenvironment: dev\n")
    tables = write(tmp_path, "t.yaml", "tables:\n  - {name: dim_store, kind: dim}\n")
    r = FakeRunner()
    rc = p.main(["--env", "dev", "--config", str(cfg), "--tables", str(tables), "--dbt-exit-code", "2"], runner=r)
    assert rc == 0 and r.calls == []
    assert "PUBLISH_SKIPPED" in capsys.readouterr().out


def test_main_exits_nonzero_on_a_publish_error(tmp_path):
    cfg = write(tmp_path, "c.yaml", "project: proj\nenvironment: dev\n")
    tables = write(tmp_path, "t.yaml", "tables:\n  - {name: dim_ghost, kind: dim}\n")
    rc = p.main(
        ["--env", "dev", "--config", str(cfg), "--tables", str(tables), "--invocation-id", "i"],
        runner=FakeRunner(),
    )
    assert rc == 1


def test_main_needs_an_invocation_id_unless_publishing_all(tmp_path):
    cfg = write(tmp_path, "c.yaml", "project: proj\nenvironment: dev\n")
    tables = write(tmp_path, "t.yaml", "tables:\n  - {name: dim_store, kind: dim}\n")
    base = ["--env", "dev", "--config", str(cfg), "--tables", str(tables), "--run-results", str(tmp_path / "none.json")]
    assert p.main(base, runner=FakeRunner()) == 1
    assert p.main(base + ["--all"], runner=FakeRunner(), ) == 0


def test_environment_mismatch_is_rejected(tmp_path):
    cfg = write(tmp_path, "c.yaml", "project: proj\nenvironment: int\n")
    tables = write(tmp_path, "t.yaml", "tables:\n  - {name: dim_store, kind: dim}\n")
    assert p.main(["--env", "dev", "--config", str(cfg), "--tables", str(tables), "--all"], runner=FakeRunner()) == 1


def test_read_invocation_id(tmp_path):
    f = write(tmp_path, "rr.json", '{"metadata": {"invocation_id": "abc"}}')
    assert p.read_invocation_id(f) == "abc"
    assert p.read_invocation_id(tmp_path / "missing.json") is None
