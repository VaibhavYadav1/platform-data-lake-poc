"""Unit tests for the change-size guard (DQ42) and helpers. Run: python -m pytest loaders/crm/tests"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crm_loader import change_ratio, folder_ts, guard_trips, md5_hex, parse_ts, read_account_pairs  # noqa: E402

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 11, 2, tzinfo=timezone.utc)


def accounts(n, changed=0):
    """n accounts; the first `changed` have a newer updated_at."""
    return {(f"A{i}", T1 if i < changed else T0) for i in range(n)}


def test_zero_percent_loads():
    r = change_ratio(accounts(100), accounts(100))
    assert r == 0 and not guard_trips(r)


def test_49_percent_loads():
    r = change_ratio(accounts(100), accounts(100, changed=49))
    assert r == 0.49 and not guard_trips(r)


def test_exactly_50_percent_loads():
    assert not guard_trips(change_ratio(accounts(100), accounts(100, changed=50)))


def test_51_percent_holds():
    r = change_ratio(accounts(100), accounts(100, changed=51))
    assert r == 0.51 and guard_trips(r)


def test_disappeared_accounts_count_as_changes():
    assert change_ratio(accounts(100), accounts(40)) == 0.60


def test_first_export_has_no_ratio_and_loads():
    r = change_ratio(set(), accounts(10))
    assert r is None and not guard_trips(r)


def test_parse_ts_and_folder_ts():
    assert parse_ts("2026-11-20T08:00:00Z") == datetime(2026, 11, 20, 8, tzinfo=timezone.utc)
    assert parse_ts("2026-11-20 08:00:00+00:00") == parse_ts("2026-11-20T08:00:00Z")
    assert parse_ts("") is None
    assert folder_ts("export_ts=20261120T080000Z") == datetime(2026, 11, 20, 8, tzinfo=timezone.utc)


def test_md5_hex_from_gcs_base64():
    assert md5_hex("1B2M2Y8AsgTpgAmY7PhCfg==") == "d41d8cd98f00b204e9800998ecf8427e"  # md5 of empty content


def test_read_account_pairs():
    data = b"account_id,updated_at\nA1,2026-11-01T00:00:00Z\nA2,\n"
    assert read_account_pairs(data) == {("A1", T0), ("A2", None)}
