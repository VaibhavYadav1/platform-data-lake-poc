"""E11: the forced failure fails only when asked, only the build step can receive it, and the
evidence tool needs nothing the test does not provide.
"""
from pathlib import Path

import pytest
import yaml

jinja2 = pytest.importorskip("jinja2")

ROOT = Path(__file__).resolve().parents[2]
TEST_SQL = ROOT / "dbt" / "tests" / "force_fail_mv_store_health.sql"
WORKFLOW = ROOT / "orchestration" / "micro_batch.workflow.yaml"


def render(**variables):
    """The SQL dbt would run, with var() answered from `variables` and ref() stubbed."""
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    return env.from_string(TEST_SQL.read_text(encoding="utf-8")).render(
        var=lambda name, default=None: variables.get(name, default),
        ref=lambda name: f"`proj.build_dev.{name}`",
    )


def rows_returned(sql):
    """A singular test fails when it returns rows. `limit 0` returns none."""
    body = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--")).strip()
    return "limit 0" not in body.lower() and body.lower().startswith("select")


# ------------------------------------------------------------------------------- the dbt test
def test_it_fails_when_force_fail_is_true():
    assert rows_returned(render(force_fail=True))


def test_it_passes_when_force_fail_is_false_or_absent():
    assert not rows_returned(render(force_fail=False))
    assert not rows_returned(render())


def test_it_depends_on_mv_store_health_without_reading_its_rows():
    """The dependency puts it mid-graph; not reading rows means an empty table cannot hide the failure."""
    sql = render(force_fail=True)
    assert "-- depends_on: `proj.build_dev.mv_store_health`" in sql
    code = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "mv_store_health" not in code


def test_the_failure_says_it_is_the_test_not_the_data():
    assert "not a data problem" in render(force_fail=True)


# --------------------------------------------------------------------------- the workflow plumbing
@pytest.fixture(scope="module")
def doc():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def step(doc, name):
    return next(s[name] for s in doc["main"]["steps"] if name in s)


def test_dbt_vars_is_optional_and_null_by_default(doc):
    init = step(doc, "init")["assign"]
    assert next(i["dbt_vars"] for i in init if "dbt_vars" in i) == '${map.get(cfg, "dbt_vars")}'


def test_default_build_arguments_are_just_microbatch(doc):
    assert step(doc, "prepare_build_args")["assign"] == [{"build_args": ["microbatch"]}]


def test_dbt_vars_become_dash_dash_vars_on_the_build(doc):
    switch = step(doc, "add_dbt_vars")["switch"][0]
    assert switch["condition"] == "${dbt_vars != null}"
    assert switch["assign"] == [{"build_args": '${["microbatch", "--vars", dbt_vars]}'}]


def test_only_the_build_step_receives_the_vars(doc):
    for name in ("freshness_src", "freshness"):
        text = yaml.safe_dump(step(doc, name))
        assert "build_args" not in text and "dbt_vars" not in text
    assert step(doc, "build_publish")["args"]["job_args"] == "${build_args}"


def test_the_arguments_are_prepared_just_before_the_build(doc):
    names = [next(iter(s)) for s in doc["main"]["steps"]]
    assert names.index("freshness_src") < names.index("prepare_build_args") < names.index("add_dbt_vars") < names.index("build_publish")
