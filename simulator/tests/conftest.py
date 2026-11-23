"""
Database tests need a PostgreSQL server where they may create and drop databases. Point SIM_TEST_PG at it, for
example `host=localhost port=5432 user=postgres password=local` (the Docker container from the Phase 0 runbook).
Without it, only the tests that need no database run.
"""

import os
import uuid
from pathlib import Path

import psycopg
import pytest

REPO = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO / "sql" / "g2" / "schema.sql"


def server_dsn():
    dsn = os.environ.get("SIM_TEST_PG")
    if not dsn:
        pytest.skip("set SIM_TEST_PG to run the database tests")
    return psycopg.conninfo.conninfo_to_dict(dsn)


@pytest.fixture
def g2_db(monkeypatch):
    """A fresh database with sql/g2/schema.sql applied; the simulator's PG_* variables point at it."""
    server = server_dsn()
    name = f"g2_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(**{**server, "dbname": server.get("dbname", "postgres")}, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    try:
        with psycopg.connect(**{**server, "dbname": name}, autocommit=True) as conn:
            conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        for var, key, default in (("PG_HOST", "host", "localhost"), ("PG_PORT", "port", "5432"),
                                  ("PG_USER", "user", "postgres"), ("PG_PASSWORD", "password", None)):
            if server.get(key, default) is None:
                monkeypatch.delenv(var, raising=False)
            else:
                monkeypatch.setenv(var, str(server.get(key, default)))
        monkeypatch.setenv("PG_DB", name)
        monkeypatch.delenv("PG_INSTANCE", raising=False)
        yield {**server, "dbname": name}
    finally:
        with psycopg.connect(**{**server, "dbname": server.get("dbname", "postgres")}, autocommit=True) as admin:
            admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
