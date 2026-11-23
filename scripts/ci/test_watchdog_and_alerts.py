"""E7: the watchdog, and the alerts that listen to it, agree with each other.

An alert only works if the log line it counts is the line something actually writes. These tests
pin the event names across the four places that must match: the macro, the watchdog workflow, the
log-based metrics and the night-off pause list.
"""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WATCHDOG = ROOT / "orchestration" / "watchdog.workflow.yaml"
MACRO = ROOT / "dbt" / "macros" / "freshness_check.sql"
MONITORING = ROOT / "terraform" / "modules" / "monitoring" / "main.tf"
WATCHDOG_TF = ROOT / "terraform" / "modules" / "workflows" / "watchdog.tf"
WORKFLOWS_VARS = ROOT / "terraform" / "modules" / "workflows" / "variables.tf"


@pytest.fixture(scope="module")
def doc():
    return yaml.safe_load(WATCHDOG.read_text(encoding="utf-8"))


def walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


# ------------------------------------------------------------------------------ the watchdog
def test_threshold_is_eight_minutes_and_interval_five(doc):
    init = next(s["init"] for s in doc["main"]["steps"] if "init" in s)["assign"]
    threshold = next(i["threshold_minutes"] for i in init if "threshold_minutes" in i)
    assert threshold.endswith(", 8)}")
    assert re.search(r'watchdog_interval_minutes"\s*{[^}]*default\s*=\s*5\b', WORKFLOWS_VARS.read_text(encoding="utf-8"), re.S)


def test_one_query_reads_both_sources_with_a_partition_filter(doc):
    calls = [n for n in walk(doc["main"]) if isinstance(n, dict) and n.get("call") == "googleapis.bigquery.v2.jobs.query"]
    assert len(calls) == 1
    init = next(s["init"] for s in doc["main"]["steps"] if "init" in s)["assign"]
    # The query is built from several assignments (one expression may not exceed 400 characters).
    sql = " ".join(str(v) for i in init for k, v in i.items() if k.startswith(("sql_", "heartbeat_table", "case_event_table")))
    assert "g2_heartbeat" in sql and "case_event" in sql
    assert "publish_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)" in sql


def test_a_stale_source_logs_watchdog_stale_at_error(doc):
    logs = [
        n for n in walk(doc["judge"])
        if isinstance(n, dict) and n.get("call") == "sys.log" and n["args"]["json"].get("event") == "watchdog_stale"
    ]
    assert len(logs) == 2  # no rows, and too old
    assert all(n["args"]["severity"] == "ERROR" for n in logs)


def test_both_sources_are_judged(doc):
    judged = [
        s[name]["args"]["source_name"]
        for s in doc["main"]["steps"]
        for name in s
        if s[name].get("call") == "judge"
    ]
    assert judged == ["simulator", "case_event"]


def test_no_reserved_variable_names(doc):
    reserved = {"env"}  # add a word whenever Workflows rejects one at deploy time
    assigned = set()
    for workflow in doc.values():
        assigned |= set(workflow.get("params", []))
        for node in walk(workflow["steps"]):
            if isinstance(node, dict) and isinstance(node.get("assign"), list):
                for item in node["assign"]:
                    assigned |= set(item)
    assert not assigned & reserved


# ------------------------------------------------------------------- the alerts listen to it
def metric_events():
    text = MONITORING.read_text(encoding="utf-8")
    block = text.split("log_events = {")[1].split("}")[0]
    return set(re.findall(r"^\s*(\w+)\s*=", block, re.M))


def test_metrics_exist_for_the_three_logged_events():
    assert metric_events() == {"freshness_breach", "watchdog_stale", "crm_guard_tripped"}


def test_metric_names_match_what_is_actually_logged():
    assert "freshness_breach" in MACRO.read_text(encoding="utf-8")
    assert "watchdog_stale" in WATCHDOG.read_text(encoding="utf-8")


def test_four_alert_policies_exist():
    text = MONITORING.read_text(encoding="utf-8")
    assert 'resource "google_monitoring_alert_policy" "workflow_failed"' in text
    assert 'resource "google_monitoring_alert_policy" "event"' in text
    policies = re.findall(r"^\s{4}(\w+) = {\s*\n\s+title", text, re.M)
    assert set(policies) == {"freshness_breach", "watchdog_stale", "crm_guard_tripped"}


def test_failure_alert_watches_every_poc_workflow_and_only_failures():
    text = MONITORING.read_text(encoding="utf-8")
    assert "workflows.googleapis.com/finished_execution_count" in text
    assert 'metric.labels.status=\\"FAILED\\"' in text
    variables = (MONITORING.parent / "variables.tf").read_text(encoding="utf-8")
    assert 'default     = "poc-.*"' in variables


# ----------------------------------------------------------------- night-off pauses the watchdog
def test_night_off_pauses_the_job_this_module_creates():
    assert 'name        = "poc-watchdog"' in WATCHDOG_TF.read_text(encoding="utf-8")
    assert '"poc-watchdog"' in WORKFLOWS_VARS.read_text(encoding="utf-8")
    assert "ignore_changes = [paused]" in WATCHDOG_TF.read_text(encoding="utf-8")


# ------------------------------------------- limits Workflows and Monitoring only enforce when deployed
ORCHESTRATION = ROOT / "orchestration"


@pytest.mark.parametrize("path", sorted(ORCHESTRATION.glob("*.workflow.yaml")), ids=lambda p: p.name)
def test_no_expression_is_longer_than_400_characters(path):
    """Workflows rejects a longer expression with a parse error, and only when it is deployed."""
    tree = yaml.safe_load(path.read_text(encoding="utf-8"))
    too_long = [
        s[:60] + "..."
        for node in walk(tree)
        if isinstance(node, str)
        for s in [node.strip()]
        if s.startswith("${") and s.endswith("}") and len(s) - 3 > 400
    ]
    assert not too_long, too_long


def test_every_alert_filter_restricts_resource_type():
    """Monitoring rejects an alert filter without resource.type, also for log-based metrics."""
    text = MONITORING.read_text(encoding="utf-8")
    blocks = text.split("condition_threshold {")[1:]
    assert len(blocks) == 2  # the workflow policy, and the one block shared by the three event policies
    for block in blocks:
        filter_part = block.split("aggregations {")[0]
        assert "resource.type" in filter_part


def test_no_notification_rate_limit_on_metric_threshold_policies():
    """Monitoring allows it only on policies that match log lines directly."""
    assert "notification_rate_limit {" not in MONITORING.read_text(encoding="utf-8")
