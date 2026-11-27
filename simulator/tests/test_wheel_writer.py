"""Tests for the sim_g2_datalake schema and writer's pure functions (task A9). No GCP access."""
import random
import re
from datetime import datetime, timezone

import pytest

from simulator.config import LakeSettings
from simulator.create_sim_g2_datalake import TABLES, main
from simulator.wheel_writer import WheelWriterError, build_wheels, generate_events

NOW = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)


def test_lake_settings_defaults_and_overrides():
    assert LakeSettings.from_env({}) == LakeSettings("gks-datalake-poc2-dev", "sim_g2_datalake", "us-central1",
                                                     "gks-datalake-poc2-dev", "raw_g2")
    assert LakeSettings.from_env({"GCP_PROJECT": "p1"}).project == "p1"
    s = LakeSettings.from_env({"GCP_PROJECT": "p1", "G2DL_PROJECT": "lake"})
    assert (s.project, s.raw_g2_project) == ("lake", "p1")  # lake in a second project; raw_g2 stays in the main one


def test_tables_match_dbt_sources():
    assert set(TABLES) == {"wheel", "wheel_event", "derived_alert"}
    assert {c.name for c in TABLES["wheel"].columns} >= {"wheel_id", "g2_store_id", "cart_id", "installed_at", "status"}
    assert TABLES["wheel_event"].partition_field == "event_ts"
    assert "_loaded_at" in {c.name for c in TABLES["wheel_event"].columns}


def test_dry_run_needs_no_gcp(capsys):
    assert main(["--dry-run"]) == 0
    assert "table wheel_event" in capsys.readouterr().out


def test_build_wheels_deterministic_and_shaped():
    a, b = build_wheels(["S102", "S101"]), build_wheels(["S101", "S102"])
    assert a == b and len(a) == 40
    assert all(re.fullmatch(r"W\d{5}", r["wheel_id"]) and re.fullmatch(r"C\d{5}", r["cart_id"]) for r in a)
    assert len({r["wheel_id"] for r in a}) == 40
    assert {r["status"] for r in a} <= {"ACTIVE", "INACTIVE"}


def test_generate_events_shape_and_unknown_wheels():
    ids = [r["wheel_id"] for r in build_wheels([f"S{i}" for i in range(101, 141)])]
    rows = generate_events(ids, NOW, random.Random(1))
    assert 50 <= len(rows) <= 200
    assert len({r["event_id"] for r in rows}) == len(rows)
    assert {r["event_type"] for r in rows} <= {"LOCK", "UNLOCK", "EXIT_ATTEMPT", "LOW_BATTERY"}
    many = generate_events(ids, NOW, random.Random(2), rate=200)
    unknown = sum(r["wheel_id"] not in set(ids) for r in many) / len(many)
    assert 0.001 < unknown < 0.015


def test_generate_events_without_wheels_fails():
    with pytest.raises(WheelWriterError):
        generate_events([], NOW, random.Random(1))
