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


# ---- file and manifest checks -------------------------------------------------------------------------

import pytest  # noqa: E402

from crm_loader import LoaderError, check_csv, manifest_ts  # noqa: E402

TS = datetime(2026, 11, 20, 8, tzinfo=timezone.utc)
STORE_HEADER = "crm_store_id,account_id,g2_store_id,status,updated_at,export_ts"


def store_csv(*rows, header=STORE_HEADER):
    return ("\n".join([header, *rows]) + "\n").encode()


def test_check_csv_counts_rows():
    data = store_csv("C1,A1,G1,Active,2026-11-01T00:00:00Z,2026-11-20T08:00:00Z",
                     "C2,A2,G2,Active,2026-11-01T00:00:00Z,2026-11-20T08:00:00Z")
    assert check_csv("store.csv", data, TS) == 2


def test_check_csv_header_only_is_zero_rows():
    assert check_csv("store.csv", store_csv(), TS) == 0


def test_check_csv_rejects_wrong_header():
    with pytest.raises(LoaderError, match="header"):
        check_csv("store.csv", store_csv(header="crm_store_id,account_id"), TS)


def test_check_csv_rejects_empty_file():
    with pytest.raises(LoaderError, match="empty file"):
        check_csv("store.csv", b"", TS)


def test_check_csv_rejects_other_exports_rows():
    data = store_csv("C1,A1,G1,Active,2026-11-01T00:00:00Z,2026-11-20T07:00:00Z")
    with pytest.raises(LoaderError, match="export_ts"):
        check_csv("store.csv", data, TS)


def test_check_csv_rejects_missing_or_garbled_export_ts():
    with pytest.raises(LoaderError, match="export_ts"):
        check_csv("store.csv", store_csv("C1,A1,G1,Active,2026-11-01T00:00:00Z,"), TS)
    with pytest.raises(LoaderError, match="export_ts"):
        check_csv("store.csv", store_csv("C1,A1,G1,Active,2026-11-01T00:00:00Z,garbage"), TS)


def test_check_csv_rejects_short_row():
    with pytest.raises(LoaderError, match="values"):
        check_csv("store.csv", store_csv("C1,A1"), TS)


def test_manifest_ts_accepts_folder_and_iso_formats():
    assert manifest_ts("20261120T080000Z") == TS
    assert manifest_ts("2026-11-20T08:00:00Z") == TS
    assert manifest_ts("nonsense") is None
