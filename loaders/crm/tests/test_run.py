"""run(): exactly-once loading, the HELD stop, retries. GCS and BigQuery are replaced by in-memory fakes.
Run: python -m pytest loaders/crm/tests"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import crm_loader  # noqa: E402
from crm_loader import FAILED, HELD, LOADED, State  # noqa: E402

ARGS = ("b", "crm", "p", "d", "l")


def ts(h):
    return datetime(2026, 11, 26, h, tzinfo=timezone.utc)


class FakeWarehouse:
    """Landing tables as {export_ts: {file: rows}} and a log as a list; the same calls as Warehouse."""

    def __init__(self, states=None, accounts=None):
        self._states = dict(states or {})
        self.accounts = accounts or {}      # export_ts -> account pairs, for the guard
        self.landed = {}                    # export_ts -> {file: rows}
        self.log_rows = []                  # (export_ts, status)
        self.loads = []                     # export_ts of every file load
        self.fail_load_for = set()
        self.extra_rows = {}                # export_ts -> rows another loader added

    def states(self):
        return dict(self._states)

    def last_loaded_accounts(self, states):
        loaded = [t for t, s in states.items() if s.status == LOADED]
        return self.accounts.get(max(loaded), set()) if loaded else set()

    def delete_export(self, t):
        self.landed.pop(t, None)

    def load_csv(self, uri, table):
        stamp = uri.split("export_ts=")[1].split("/")[0]
        t = datetime.strptime(stamp, crm_loader.TS_FORMAT).replace(tzinfo=timezone.utc)
        self.loads.append(t)
        if t in self.fail_load_for:
            raise RuntimeError("load job failed")
        self.landed.setdefault(t, {})[uri.rsplit("/", 1)[1]] = 5 + self.extra_rows.get(t, 0)
        return 5

    def count_export(self, t):
        return dict(self.landed.get(t, {}))

    def log(self, t, folder, status, *, approved=False, **kw):
        self.log_rows.append((t, status))
        self._states[t] = State(status, approved)


class Env:
    folders = []


@pytest.fixture
def env(monkeypatch):
    e = Env()
    monkeypatch.setattr(crm_loader.storage, "Client", lambda **kw: object())
    monkeypatch.setattr(crm_loader, "discover", lambda gcs, b, p: {t: {} for t in e.folders})
    monkeypatch.setattr(crm_loader, "validate", lambda files, t: {n: b"" for n in crm_loader.FILE_TABLE})
    monkeypatch.setattr(crm_loader, "check_csv", lambda n, data, t: 5)
    monkeypatch.setattr(crm_loader, "read_account_pairs", lambda data: set())
    monkeypatch.setattr(crm_loader, "change_ratio", lambda prev, cur: None)
    return e


def use(monkeypatch, wh):
    monkeypatch.setattr(crm_loader, "Warehouse", lambda *a: wh)


def test_loads_each_export_once_and_skips_loaded_ones(env, monkeypatch):
    env.folders = [ts(7), ts(8)]
    wh = FakeWarehouse(states={ts(7): State(LOADED, False)})
    use(monkeypatch, wh)
    assert crm_loader.run(*ARGS, None) == 0
    assert wh.loads == [ts(8)] * 3                      # 07:00 untouched, 08:00 loaded once per file
    assert crm_loader.run(*ARGS, None) == 0
    assert wh.loads == [ts(8)] * 3                      # a second run loads nothing
    assert wh.log_rows == [(ts(8), LOADED)]


def test_held_export_stops_the_later_ones_but_exits_0(env, monkeypatch):
    env.folders = [ts(7), ts(8), ts(9)]
    wh = FakeWarehouse(states={ts(6): State(LOADED, False)}, accounts={ts(6): {("a", None)}})
    use(monkeypatch, wh)
    monkeypatch.setattr(crm_loader, "change_ratio", lambda prev, cur: 0.9)
    assert crm_loader.run(*ARGS, None) == 0             # exit 0: the workflow goes on to dbt
    assert wh.log_rows == [(ts(7), HELD)] and wh.loads == []
    assert crm_loader.run(*ARGS, None) == 0             # still held, not approved: still stops
    assert wh.loads == [] and wh.log_rows == [(ts(7), HELD)]


def test_held_is_released_only_by_approve(env, monkeypatch):
    env.folders = [ts(7), ts(8)]
    wh = FakeWarehouse(states={ts(7): State(HELD, False)})
    use(monkeypatch, wh)
    assert crm_loader.run(*ARGS, None) == 0 and wh.loads == []
    assert crm_loader.run(*ARGS, "export_ts=20261126T070000Z") == 0
    assert wh.states()[ts(7)].approved and wh.loads == []   # approving loads nothing by itself
    assert crm_loader.run(*ARGS, None) == 0
    assert set(wh.loads) == {ts(7), ts(8)}                  # now 07:00, then 08:00


def test_approve_refuses_an_export_that_is_not_held(env, monkeypatch):
    wh = FakeWarehouse(states={ts(7): State(LOADED, False)})
    use(monkeypatch, wh)
    assert crm_loader.run(*ARGS, "export_ts=20261126T070000Z") == 1
    assert crm_loader.run(*ARGS, "export_ts=20261126T100000Z") == 1


def test_failed_export_is_cleaned_logged_and_retried_next_run(env, monkeypatch):
    env.folders = [ts(7), ts(8)]
    wh = FakeWarehouse()
    wh.fail_load_for = {ts(7)}
    use(monkeypatch, wh)
    assert crm_loader.run(*ARGS, None) == 1             # exit 1: the workflow fails and dbt does not run
    assert wh.log_rows == [(ts(7), FAILED)] and ts(7) not in wh.landed
    assert ts(8) not in wh.loads                        # nothing newer is loaded past a failure
    wh.fail_load_for = set()
    assert crm_loader.run(*ARGS, None) == 0             # the next run retries 07:00, then 08:00
    assert [s for t, s in wh.log_rows] == [FAILED, LOADED, LOADED]
    assert all(len(wh.landed[t]) == 3 for t in (ts(7), ts(8)))


def test_leftover_rows_from_a_run_that_died_before_logging_are_removed(env, monkeypatch):
    env.folders = [ts(7)]
    wh = FakeWarehouse()
    wh.landed[ts(7)] = {"account.csv": 5, "store.csv": 5, "work_order.csv": 5}   # loaded, never logged
    use(monkeypatch, wh)
    assert crm_loader.run(*ARGS, None) == 0
    assert wh.landed[ts(7)] == {"account.csv": 5, "store.csv": 5, "work_order.csv": 5}   # 5 each, not 10


def test_a_concurrent_loader_doubling_the_rows_fails_the_run(env, monkeypatch):
    env.folders = [ts(7)]
    wh = FakeWarehouse()
    wh.extra_rows = {ts(7): 5}                          # the tables end up with 10, the files have 5
    use(monkeypatch, wh)
    assert crm_loader.run(*ARGS, None) == 1
    assert wh.log_rows == [(ts(7), FAILED)] and ts(7) not in wh.landed


def test_an_export_without_a_manifest_is_never_seen():
    class Blob:
        def __init__(self, name):
            self.name = name

    class Gcs:
        def list_blobs(self, bucket, prefix=None):
            return [Blob("crm/export_ts=20261126T070000Z/account.csv"), Blob("crm/export_ts=20261126T070000Z/store.csv")]

    assert crm_loader.discover(Gcs(), "b", "crm") == {}
