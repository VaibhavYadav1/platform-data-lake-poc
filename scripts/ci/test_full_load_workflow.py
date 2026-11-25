"""E6: the full-load workflow starts the right job with the right argument, and the rules every
workflow must follow (Workflows only enforces them when the file is deployed).
"""
from pathlib import Path

import pytest
import yaml

ORCH = Path(__file__).resolve().parents[2] / "orchestration"
FILE = ORCH / "full_load.workflow.yaml"
ALL = sorted(ORCH.glob("*.workflow.yaml"))


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


@pytest.fixture(scope="module")
def doc():
    return load(FILE)


def step(doc, name):
    return next(s[name] for s in doc["main"]["steps"] if name in s)


# ------------------------------------------------------------------ what makes it a "full load"
def test_it_starts_the_dbt_job_with_the_fullload_argument(doc):
    run = step(doc, "run_fullload")
    assert run["try"]["call"] == "googleapis.run.v2.projects.locations.jobs.run"
    override = run["try"]["args"]["body"]["overrides"]["containerOverrides"][0]
    assert override["args"] == ["fullload"]  # micro-batch starts the same job with ["microbatch"]


def test_the_job_is_the_dbt_runner_of_the_environment(doc):
    init = step(doc, "init")["assign"]
    job = next(i["dbt_job"] for i in init if "dbt_job" in i)
    assert '"poc-dbt-runner-" + env_name' in job


def test_the_workflows_run_id_is_passed_to_the_job(doc):
    override = step(doc, "run_fullload")["try"]["args"]["body"]["overrides"]["containerOverrides"][0]
    assert {"name": "RUN_ID", "value": "${run_id}"} in override["env"]


def test_the_connector_waits_longer_than_the_job_may_run(doc):
    args = step(doc, "run_fullload")["try"]["args"]
    assert "timeout_seconds + 300" in args["connector_params"]["timeout"]
    assert args["body"]["overrides"]["timeout"].startswith("${string(timeout_seconds)")


def test_there_is_no_hand_written_polling(doc):
    """jobs.run already waits and raises on failure; polling it by hand was the wrong approach."""
    calls = {n.get("call") for n in walk(doc) if isinstance(n, dict)}
    assert "googleapis.run.v2.projects.locations.jobs.executions.get" not in calls
    assert "check_job_completion" not in doc


def test_failure_is_logged_then_raised_and_success_is_logged(doc):
    except_steps = [name for s in step(doc, "run_fullload")["except"]["steps"] for name in s]
    assert except_steps == ["log_failed", "raise_failure"]
    names = [next(iter(s)) for s in doc["main"]["steps"]]
    assert names.index("run_fullload") < names.index("log_succeeded") < names.index("done")


def test_the_log_row_is_written_without_sql(doc):
    calls = [n.get("call") for n in walk(doc["log_result"]) if isinstance(n, dict)]
    assert "googleapis.bigquery.v2.tabledata.insertAll" in calls
    assert "googleapis.bigquery.v2.jobs.insert" not in calls


# --------------------------------------------------- rules every workflow must follow at deploy
@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_no_text_is_interpolated_inside_a_longer_string(path):
    """Workflows evaluates ${...} only when it is the WHOLE value, so "a ${x} b" stays literal."""
    bad = [
        s[:70]
        for node in walk(load(path))
        if isinstance(node, str)
        for s in [node.strip()]
        if "${" in s and not (s.startswith("${") and s.endswith("}"))
    ]
    assert not bad, bad


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_no_reserved_variable_names(path):
    reserved = {"env"}  # add a word whenever Workflows rejects one at deploy time
    assigned = set()
    for workflow in load(path).values():
        assigned |= set(workflow.get("params", []))
        for node in walk(workflow["steps"]):
            if isinstance(node, dict) and isinstance(node.get("assign"), list):
                for item in node["assign"]:
                    assigned |= set(item)
    assert not assigned & reserved, (path.name, assigned & reserved)


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_main_tolerates_no_arguments(path):
    """gcloud workflows run with no --data passes null; map.get(null, ...) would fail."""
    text = path.read_text(encoding="utf-8")
    assert "args != null" in text
    assert 'map.get(args,' not in text
