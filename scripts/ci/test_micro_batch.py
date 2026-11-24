"""E4: the micro-batch workflow keeps the plan's step order and logs every step.

These are structural checks on the YAML. They cannot prove the workflow runs (that needs the
Cloud Run jobs from E3), but they catch the mistakes that are cheap to make and costly to find
in the cloud: a step moved, a freshness failure that stops the build, a job that is not logged.
"""
from pathlib import Path

import pytest
import yaml

FILE = Path(__file__).resolve().parents[2] / "orchestration" / "micro_batch.workflow.yaml"


@pytest.fixture(scope="module")
def doc():
    return yaml.safe_load(FILE.read_text(encoding="utf-8"))


def steps_of(workflow):
    return workflow["steps"]


def name_of(step):
    return next(iter(step))


def walk(node):
    """Yield every dict and list nested in node."""
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def step_names(workflow):
    """Names of every step in a (sub)workflow, nested ones included."""
    names = list(map(name_of, workflow["steps"]))
    for node in walk(workflow["steps"]):
        # Only a list under a `steps:` key holds steps; `assign:` lists look similar but are not.
        if isinstance(node, dict) and isinstance(node.get("steps"), list):
            names += [name_of(s) for s in node["steps"]]
    return names


def main_step(doc, name):
    return next(s[name] for s in steps_of(doc["main"]) if name in s)


def test_plan_step_order(doc):
    order = ["init", "ensure_log_table", "single_run", "load_crm", "freshness_src", "build_publish", "freshness"]
    names = [name_of(s) for s in steps_of(doc["main"])]
    positions = [names.index(s) for s in order]
    assert positions == sorted(positions), names


def test_build_publish_runs_microbatch_and_fails_the_workflow(doc):
    step = main_step(doc, "build_publish")
    assert step["call"] == "run_job"
    assert step["args"]["job_args"] == "${build_args}"
    assert main_step(doc, "prepare_build_args")["assign"] == [{"build_args": ["microbatch"]}]
    assert step["args"]["warn_only"] is False


def test_source_freshness_is_warn_only(doc):
    step = main_step(doc, "freshness_src")
    assert step["args"]["job_args"][:3] == ["dbt", "source", "freshness"]
    assert step["args"]["warn_only"] is True


def test_freshness_check_runs_after_publish_with_run_operation(doc):
    names = [name_of(s) for s in steps_of(doc["main"])]
    assert names.index("freshness") > names.index("build_publish")
    inner = main_step(doc, "freshness")["switch"][0]["steps"][0]["run_freshness_check"]
    assert inner["args"]["job_args"][:3] == ["dbt", "run-operation", "freshness_check"]


def test_crm_loader_is_gated_by_run_crm_loader(doc):
    cases = main_step(doc, "load_crm")["switch"]
    assert cases[0]["condition"] == "${run_crm_loader}"
    assert cases[0]["steps"][0]["run_crm_loader_job"]["args"]["warn_only"] is False
    # when it is off the skip is still logged
    assert cases[1]["steps"][0]["log_load_crm_skipped"]["call"] == "log_step"


def test_every_job_step_is_logged_by_run_job(doc):
    run_job = doc["run_job"]
    calls = [n["call"] for n in walk(run_job["steps"]) if isinstance(n, dict) and "call" in n]
    assert calls.count("log_step") == 2  # one on failure, one on success
    assert any(n.get("raise") for n in walk(run_job["steps"]) if isinstance(n, dict))


def test_run_job_only_warns_when_asked(doc):
    failure = next(
        s["run"]["except"]["steps"] for s in doc["run_job"]["steps"] if "run" in s
    )
    names = [name_of(s) for s in failure]
    assert names == ["log_failure", "warn_and_go_on", "raise_failure"]
    assert failure[1]["warn_and_go_on"]["switch"][0]["condition"] == "${warn_only}"


def test_skipped_overlap_returns_before_any_job(doc):
    names = [name_of(s) for s in steps_of(doc["main"])]
    skip_at = names.index("single_run")
    job_calls = [i for i, s in enumerate(steps_of(doc["main"])) if s[name_of(s)].get("call") == "run_job"]
    assert all(i > skip_at for i in job_calls)
    returns = [n for n in walk(main_step(doc, "single_run")) if isinstance(n, dict) and "return_skipped" in n]
    assert returns


def test_all_calls_resolve(doc):
    subworkflows = {k for k in doc if k != "main"}
    for node in walk(doc):
        if isinstance(node, dict) and "call" in node:
            target = node["call"]
            assert target in subworkflows or target.startswith(("googleapis.", "sys.", "http.")), target


def test_step_names_are_unique_within_each_workflow(doc):
    for name, workflow in doc.items():
        names = step_names(workflow)
        assert len(names) == len(set(names)), (name, sorted(n for n in names if names.count(n) > 1))


def test_no_hard_coded_environment(doc):
    """One file serves dev and int: the environment comes from POC_ENV or args."""
    text = FILE.read_text(encoding="utf-8")
    assert "ops_dev" not in text and "ops_int" not in text
    assert "gks-datalake" not in text


def test_no_reserved_variable_names(doc):
    """Workflows rejects a variable named like a reserved word, and only at deploy time."""
    reserved = {"env"}  # add a word here whenever Workflows rejects one
    assigned = set()
    for workflow in doc.values():
        assigned |= set(workflow.get("params", []))
        for node in walk(workflow["steps"]):
            if isinstance(node, dict) and isinstance(node.get("assign"), list):
                for item in node["assign"]:
                    assigned |= set(item)
    assert not assigned & reserved, assigned & reserved
