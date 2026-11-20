"""E8: the order of the night-off and morning-on steps is the whole point.

Pausing the stream after the database is stopped, or stopping the database while the stream is
still running, fills the replication slot's disk or breaks the stream. These tests keep the
steps in the order the plan gives.
"""
from pathlib import Path

import pytest
import yaml

ORCH = Path(__file__).resolve().parents[2] / "orchestration"


def main_steps(name):
    doc = yaml.safe_load((ORCH / name).read_text(encoding="utf-8"))
    return [next(iter(s)) for s in doc["main"]["steps"]]


@pytest.mark.parametrize("name", ["night_off.workflow.yaml", "morning_on.workflow.yaml"])
def test_files_parse_and_have_main(name):
    doc = yaml.safe_load((ORCH / name).read_text(encoding="utf-8"))
    assert "steps" in doc["main"]


def test_night_off_order():
    steps = main_steps("night_off.workflow.yaml")
    order = ["pause_scheduler_jobs", "pause_stream", "stop_sql"]
    assert [steps.index(s) for s in order] == sorted(steps.index(s) for s in order)


def test_pause_stream_waits_for_paused_state():
    """stop_sql comes after pause_stream, which only returns once the stream is PAUSED."""
    doc = yaml.safe_load((ORCH / "night_off.workflow.yaml").read_text(encoding="utf-8"))
    step = next(s["pause_stream"] for s in doc["main"]["steps"] if "pause_stream" in s)
    assert step["call"] == "set_stream_state"
    assert step["args"]["wanted"] == "PAUSED"


def test_no_nonexistent_datastream_connector():
    for name in ("night_off.workflow.yaml", "morning_on.workflow.yaml"):
        assert "googleapis.datastream" not in (ORCH / name).read_text(encoding="utf-8")


def test_morning_on_order():
    steps = main_steps("morning_on.workflow.yaml")
    order = [
        "start_sql",
        "wait_sql_runnable",
        "resume_stream",
        "resume_simulator",
        "wait_for_first_data",
        "resume_delayed",
    ]
    idx = [steps.index(s) for s in order]
    assert idx == sorted(idx)
