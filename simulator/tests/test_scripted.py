"""Against a real PostgreSQL (SIM_TEST_PG): seed, the three batches, the expected files and the guards."""

import psycopg
import pytest

from simulator import baseline
from simulator.cli import main
from simulator.seed import SeedError, seed


def seed_args(*extra):
    return ["seed", "--batch", baseline.BATCH, *extra]


def test_seed_then_batches_match_the_expected_files(g2_db):
    assert main(seed_args()) == 0
    with psycopg.connect(**g2_db) as conn:
        assert conn.execute("SELECT count(*) FROM g2.alert_incidents").fetchone()[0] == baseline.ROWS["alert_incidents"]
        assert conn.execute("SELECT count(*) FROM g2.stores WHERE store_id = %s",
                            (baseline.PROBE_STORE_ID,)).fetchone()[0] == 1
    for n in (1, 2, 3):
        assert main(["batch", "--n", str(n)]) == 0, f"batch {n} did not match expected/batch_{n}.json"


def test_guards(g2_db):
    assert main(["batch", "--n", "1"]) == 1  # not seeded
    assert main(seed_args()) == 0
    assert main(seed_args()) == 1  # seed once only
    assert main(["batch", "--n", "2"]) == 1  # out of order
    assert main(["batch", "--n", "1"]) == 0
    assert main(["batch", "--n", "1"]) == 1  # once only
    assert main(seed_args("--reset")) == 0  # local: start again
    assert main(["batch", "--n", "1"]) == 0  # and batch 1 matches again


def test_reset_refused_when_not_local(g2_db):
    assert main(seed_args()) == 0
    with psycopg.connect(**g2_db) as conn:
        with pytest.raises(SeedError, match="local database only"):
            seed(conn, baseline.BATCH, reset=True, local=False)  # as for Cloud SQL
        assert conn.execute("SELECT count(*) FROM g2.alert_history").fetchone()[0] == baseline.ROWS["alert_history"]
