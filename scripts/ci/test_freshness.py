"""E7: the entity registry keeps the plan's promises, and freshness_check does what it says.

The macro is rendered with plain Jinja against a fake BigQuery. That cannot prove dbt accepts it,
but it catches a syntax error, a wrong breach decision and a bad SQL string before they reach the
cloud, where the first sign would be a failed micro-batch.
"""
import csv
import datetime as dt
import json
from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "dbt" / "seeds" / "entity_registry.csv"
MACRO = ROOT / "dbt" / "macros" / "freshness_check.sql"


def registry():
    with SEED.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------------------- the seed
def test_registry_holds_the_plans_seven_entities_and_promises():
    promises = {r["entity"]: (r["promise_minutes"], r["checked_by"]) for r in registry()}
    assert promises == {
        "alert": ("20", "micro-batch"),
        "alert_history": ("20", "micro-batch"),
        "case_raw": ("5", "micro-batch"),
        "case": ("20", "micro-batch"),
        "crm_export": ("75", "micro-batch"),
        "wheel_event": ("30", "micro-batch"),
        "heartbeat": ("8", "watchdog"),
    }


def test_published_facts_name_their_partition_column():
    """wh facts require a partition filter, so freshness_check must be able to supply one."""
    for r in registry():
        if r["measured_on"].startswith("wh."):
            assert r["partition_column"], r["entity"]
        else:
            assert not r["partition_column"], r["entity"]


def test_every_measured_on_is_layer_dot_table():
    for r in registry():
        assert r["measured_on"].count(".") == 1, r["entity"]


# ------------------------------------------------------------------------------- the macro
class FakeBigQuery:
    """Answers freshness_check's queries. ages maps a table name to minutes (None = no rows)."""

    def __init__(self, ages):
        self.ages = ages
        self.queries = []
        self.printed = []

    def run_query(self, sql):
        self.queries.append(sql)
        if sql.startswith("select entity"):
            rows = [
                {
                    "entity": r["entity"],
                    "measured_on": r["measured_on"],
                    "ts_column": r["ts_column"],
                    "partition_column": r["partition_column"] or None,
                    "promise_minutes": int(r["promise_minutes"]),
                }
                for r in registry()
                if r["checked_by"] == "micro-batch"
            ]
            return type("R", (), {"rows": rows})
        if sql.startswith("select max(timestamp("):
            table = sql.split("from `")[1].split("`")[0].split(".")[-1]
            age = self.ages.get(table, 1.0)
            newest = None if age is None else dt.datetime(2026, 11, 22, tzinfo=dt.timezone.utc)
            return type("R", (), {"rows": [{"newest_ts": newest, "age_minutes": age}]})
        return type("R", (), {"rows": []})


def render(ages):
    fake = FakeBigQuery(ages)
    env = jinja2.Environment(extensions=["jinja2.ext.do"], undefined=jinja2.StrictUndefined)
    source = MACRO.read_text(encoding="utf-8") + "{{ freshness_check() }}"
    env.from_string(source).render(
        execute=True,
        target=type("T", (), {"name": "dev", "project": "proj"})(),
        invocation_id="inv-1",
        run_query=fake.run_query,
        ref=lambda name: f"`proj.build_dev.{name}`",
        print=lambda s: fake.printed.append(json.loads(s)) or "",
        tojson=json.dumps,
        **{"return": lambda v: ""},
    )
    return fake


def breaches(fake):
    return {p["entity"]: p for p in fake.printed if p["event"] == "freshness_breach"}


def test_nothing_breached_when_every_entity_is_inside_its_promise():
    fake = render({})
    assert breaches(fake) == {}
    assert len(fake.printed) == 6  # the heartbeat belongs to the watchdog


def test_a_stale_entity_prints_one_error_line():
    fake = render({"fct_alert": 25.0})
    assert list(breaches(fake)) == ["alert"]
    line = breaches(fake)["alert"]
    assert line["severity"] == "ERROR"
    assert line["age_minutes"] == 25.0 and line["promise_minutes"] == 20


def test_each_entity_uses_its_own_promise():
    # 10 minutes is fine for a 20-minute alert and a breach for the 5-minute case stream.
    fake = render({"fct_alert": 10.0, "case_event": 10.0})
    assert list(breaches(fake)) == ["case_raw"]


def test_an_empty_table_counts_as_a_breach():
    fake = render({"account_landing": None})
    assert list(breaches(fake)) == ["crm_export"]
    insert = next(q for q in fake.queries if q.startswith("insert") and "'crm_export'" in q)
    assert "cast(null as timestamp)" in insert and "cast(null as float64)" in insert and "true)" in insert


def test_wh_facts_are_read_inside_a_partition_window_and_with_the_environment():
    fake = render({})
    alert = next(q for q in fake.queries if "fct_alert`" in q and q.startswith("select max"))
    assert "`proj.wh_dev.fct_alert`" in alert
    assert "alert_date >= date_sub(current_date(), interval 3 day)" in alert


def test_raw_datasets_are_not_given_an_environment():
    fake = render({})
    case = next(q for q in fake.queries if q.startswith("select max") and "case_event" in q)
    assert "`proj.raw_lpos.case_event`" in case
    assert "where" not in case


def test_every_entity_gets_a_row_in_freshness_result():
    fake = render({})
    inserts = [q for q in fake.queries if q.startswith("insert into `proj.ops_dev.freshness_result`")]
    assert len(inserts) == 6
    assert any(q.startswith("create table if not exists `proj.ops_dev.freshness_result`") for q in fake.queries)
