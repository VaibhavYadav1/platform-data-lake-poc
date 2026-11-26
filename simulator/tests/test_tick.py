"""`tick` (task A8). The database tests need SIM_TEST_PG, like test_scripted.py."""

import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest

from simulator import baseline, tick
from simulator.cli import main


def test_tick_does_not_need_data_lake_schema():
    """The cloud image has no data-lake-schema: tick and the CLI must not import the vendored generator."""
    code = ("import sys, simulator.cli, simulator.tick; "
            "bad = [m for m in sys.modules if m.startswith(('data_lake_schema', 'simulator.vendor', "
            "'simulator.seed', 'simulator.batches'))]; print(bad); sys.exit(1 if bad else 0)")
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=Path(tick.__file__).resolve().parents[1])
    assert run.returncode == 0, run.stdout + run.stderr


def test_scaled():
    rng = random.Random(1)
    assert all(3 <= tick.scaled(rng, 3, 6, 1.0) <= 6 for _ in range(100))
    assert all(tick.scaled(rng, 3, 6, 0) == 0 for _ in range(10))
    assert all(tick.scaled(rng, 3, 6, 0.5) <= 3 for _ in range(100))


@pytest.fixture
def seeded(g2_db):
    assert main(["seed", "--batch", baseline.BATCH]) == 0
    return g2_db


def counts(conn):
    return conn.execute(
        "SELECT (SELECT count(*) FROM g2.alert_incidents), (SELECT count(*) FROM g2.alert_history), "
        "(SELECT beat_at FROM g2.heartbeat WHERE source = 'simulator')").fetchone()


def probe_rows(conn):
    return conn.execute(
        "SELECT i.*, d.* FROM g2.alert_incidents i FULL JOIN g2.device_locations d ON d.device_id = i.device_id "
        "WHERE i.device_id = %s OR i.store_id = %s OR d.device_id = %s OR d.store_id = %s ORDER BY 1",
        (baseline.PROBE_DEVICE_ID, baseline.PROBE_STORE_ID) * 2).fetchall()


def test_one_tick_changes_g2_and_beats(seeded):
    with psycopg.connect(**seeded) as conn:
        incidents, history, beat = counts(conn)
        probe = probe_rows(conn)
        result = tick.run_tick(conn, rate=1.0, rng=random.Random(7))
        incidents2, history2, beat2 = counts(conn)

        assert 3 <= len(result.opened) <= 6
        assert 3 <= len(result.updated) <= 6
        assert 2 <= len(result.closed) <= 5
        assert len(set(result.opened) | set(result.updated) | set(result.closed)) == \
            len(result.opened) + len(result.updated) + len(result.closed)  # each incident changed once per tick
        assert incidents2 == incidents + len(result.opened) - len(result.deleted)
        assert result.history_rows == len(result.opened) + len(result.updated) + len(result.closed)
        assert beat2 > beat
        assert probe_rows(conn) == probe
        assert result.case_events == "off" and result.crm_export == "no"


def test_rate_zero_only_beats(seeded):
    with psycopg.connect(**seeded) as conn:
        incidents, history, beat = counts(conn)
        result = tick.run_tick(conn, rate=0, rng=random.Random(3))
        incidents2, history2, beat2 = counts(conn)
    assert result.opened == result.updated == result.closed == []
    assert (incidents2, beat2 > beat) == (incidents - len(result.deleted), True)


def test_many_ticks_stay_valid(seeded):
    """Deletes, device moves and planted rows all happen over enough ticks, and nothing breaks."""
    rng = random.Random(11)
    seen = {"deleted": 0, "moved": 0, "planted": set()}
    with psycopg.connect(**seeded) as conn:
        probe = probe_rows(conn)
        for _ in range(150):
            r = tick.run_tick(conn, rate=1.0, rng=rng)
            seen["deleted"] += len(r.deleted)
            seen["moved"] += bool(r.moved_device)
            seen["planted"] |= set(r.planted.values())
        assert probe_rows(conn) == probe
        # every incident's history still points at an existing incident
        orphans = conn.execute("SELECT count(*) FROM g2.alert_history h LEFT JOIN g2.alert_incidents i "
                               "USING (incident_id) WHERE i.incident_id IS NULL").fetchone()[0]
        assert orphans == 0
    assert seen["deleted"] > 0 and seen["moved"] > 0 and seen["planted"]


def test_failed_step_leaves_heartbeat_stale(seeded):
    """CASE_TOPIC set but no A7 publisher: the tick fails after the G2 commit, and the heartbeat doesn't move."""
    with psycopg.connect(**seeded) as conn:
        _, _, beat = counts(conn)
        with pytest.raises(tick.TickError, match="A7"):
            tick.run_tick(conn, rate=1.0, case_topic="projects/p/topics/t", rng=random.Random(5))
        _, _, beat2 = counts(conn)
    assert beat2 == beat


def test_crm_hook_runs_on_every_tick(seeded, monkeypatch):
    """Every tick asks for the missing exports, so a delayed tick (minute 7, 25, ...) still writes the hour."""
    calls = []
    monkeypatch.setattr(tick, "write_crm_export", lambda bucket, prefix, now: calls.append(now) or "gs://b/crm/x")
    with psycopg.connect(**seeded) as conn:
        tick.run_tick(conn, rate=0, crm_bucket="b", now=datetime(2026, 11, 25, 10, 7, tzinfo=timezone.utc))
        r = tick.run_tick(conn, rate=0, crm_bucket="b", now=datetime(2026, 11, 25, 11, 2, tzinfo=timezone.utc))
    assert len(calls) == 2 and r.crm_export == "gs://b/crm/x"
    with psycopg.connect(**seeded) as conn:
        r = tick.run_tick(conn, rate=0, crm_bucket=None, now=datetime(2026, 11, 25, 12, 2, tzinfo=timezone.utc))
    assert len(calls) == 2 and r.crm_export == "no"  # no bucket: the export stays off


def test_cli_tick(seeded, monkeypatch):
    monkeypatch.setenv("RATE", "1.0")
    monkeypatch.delenv("CASE_TOPIC", raising=False)
    monkeypatch.delenv("CRM_BUCKET", raising=False)
    monkeypatch.delenv("G2DL_PROJECT", raising=False)
    assert main(["tick"]) == 0
    monkeypatch.setenv("G2DL_PROJECT", "some-project")  # A9 not built: refuse rather than pretend
    assert main(["tick"]) == 1
