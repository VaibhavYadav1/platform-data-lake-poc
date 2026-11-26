"""store_access.py without a database: a fake connection records the SQL and plays the primary key."""

from contextlib import contextmanager

import pytest

from simulator import store_access as sa


class FakeCursor:
    def __init__(self, rows):
        self.rows, self.calls, self.rowcount = rows, [], 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.calls.append((sql, params))
        key = tuple(params)
        if sql.startswith("INSERT"):
            self.rowcount = 0 if key in self.rows else 1
            self.rows.add(key)
        elif sql.startswith("DELETE"):
            self.rowcount = 1 if key in self.rows else 0
            self.rows.discard(key)


class FakeConn:
    def __init__(self):
        self.rows, self.cursors, self.transactions = set(), [], 0

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield

    def cursor(self):
        c = FakeCursor(self.rows)
        self.cursors.append(c)
        return c


A = "sa-tenant-a-user@gks-datalake-poc2-dev.iam.gserviceaccount.com"


def test_grant_is_idempotent_and_uses_parameters():
    cur = FakeCursor(set())
    assert sa.grant(cur, A, "ACC00001") is True
    assert sa.grant(cur, A, "ACC00001") is False
    sql, params = cur.calls[0]
    assert "ON CONFLICT (principal, crm_account_id) DO NOTHING" in sql and "%s" in sql
    assert params == (A, "ACC00001") and A not in sql


def test_revoke_reports_whether_a_row_was_removed():
    cur = FakeCursor({(A, "ACC00001")})
    assert sa.revoke(cur, A, "ACC00001") is True
    assert sa.revoke(cur, A, "ACC00001") is False
    assert cur.calls[0][0].startswith("DELETE FROM g2.store_access WHERE principal = %s")


@pytest.mark.parametrize("bad", ["", "no-at-sign", "a b@x.com", "a@b", None])
def test_principal_must_be_an_email(bad):
    with pytest.raises(sa.StoreAccessError):
        sa.grant(FakeCursor(set()), bad, "ACC00001")


def test_seed_rows_cover_both_tenants_and_the_two_proof_rows():
    rows = sa.seed_rows("proj")
    assert len(rows) == 6 and all(p.endswith("@proj.iam.gserviceaccount.com") for p, _, _ in rows)
    accounts = {(p.split("@")[0], a) for p, a, _ in rows}
    assert {("sa-tenant-a-user", "ACC00001"), ("sa-app-tenant-a", "ACC00001"),
            ("sa-tenant-b-user", "ACC00005"), ("sa-app-tenant-b", "ACC00005"),
            ("sa-tenant-a-user", "ACC00002"), ("sa-tenant-b-user", "ACC00031")} == accounts


def test_seed_is_one_transaction_and_rerun_adds_nothing():
    conn = FakeConn()
    assert sa.seed_store_access(conn, log=lambda *_: None) == 6
    assert sa.seed_store_access(conn, log=lambda *_: None) == 0
    assert conn.transactions == 2 and len(conn.rows) == 6


def test_dry_run_touches_nothing():
    lines = []
    assert sa.seed_store_access(None, dry_run=True, log=lines.append) == 0
    assert len(lines) == 6 and all(line.strip().startswith("would grant") for line in lines)


def test_run_returns_exit_codes():
    conn, out = FakeConn(), []
    assert sa.run(conn, "grant", A, "ACC00001", log=out.append) == 0
    assert sa.run(conn, "revoke", A, "ACC00001", log=out.append) == 0
    assert sa.run(conn, "revoke", A, "ACC00001", log=out.append) == 0
    assert out == [f"granted: {A} -> ACC00001", f"revoked: {A} -> ACC00001", f"nothing to revoke: {A} -> ACC00001"]
    assert sa.run(conn, "grant", "bad", "ACC00001", log=out.append) == 1
