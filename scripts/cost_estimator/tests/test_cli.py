import json

import pytest

import main
from pricing_api import CatalogClient
from conftest import client_for


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch, catalog):
    monkeypatch.setattr(main, "make_client", lambda: client_for(catalog))


def run(capsys, *argv):
    rc = main.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_estimate_from_flags_prints_the_future_cost_report(capsys, book):
    rc, out, err = run(capsys, "estimate", "--storage-size", "5", "--storage-unit", "TiB", "--queries-per-day", "200", "--operating-days", "22",
                       "--query-size", "50", "--query-unit", "GiB")
    assert rc == 0 and "# Estimated Future Cost: BigQuery" in out
    sp = book.get("storage_active_logical")
    storage = (5 * 1024 * 730 * 3600 * 2 ** 30 / sp.base_unit_factor - 10) * sp.list_unit_price
    query = (200 * 22 * 50 / 1024 - 1) * book.get("analysis").list_unit_price
    assert "%s USD" % "{:,.2f}".format(storage + query) in out
    assert "N/A (not requested)" in out and err == ""


def test_enterprise_and_bi_engine_are_only_included_when_asked(capsys):
    _, out, _ = run(capsys, "estimate", "--storage-size", "1", "--storage-unit", "TiB")
    assert "slot-hours" not in out.lower() and "GiB-hours" not in out
    rc, out, _ = run(capsys, "estimate", "--storage-size", "1", "--storage-unit", "TiB", "--enterprise", "--enterprise-slots", "100", "--enterprise-hours-per-day", "8",
                     "--enterprise-days-per-month", "22", "--bi-engine", "--bi-capacity", "10", "--bi-unit", "GiB", "--bi-hours-per-day", "8", "--bi-days-per-month", "22")
    assert rc == 0 and "Slot-hours per month: 17,600.00" in out and "GiB-hours per month: 1,760.00" in out


def test_config_file_and_flags_merge_with_flags_winning(capsys, tmp_path):
    cfg = tmp_path / "usage.json"
    cfg.write_text(json.dumps({"queries": {"per_day": 100, "operating_days": 20, "avg_data_per_query": 1, "unit": "GiB"}, "storage": {"size": 1, "unit": "GiB"}}), encoding="utf-8")
    rc, out, _ = run(capsys, "estimate", "--config", str(cfg), "--queries-per-month", "7000", "--format", "json")
    data = json.loads(out)
    assert rc == 0
    q = next(c for c in data["components"] if c["key"] == "on_demand")
    assert ["Queries per month", "7,000 (7000 queries a month)"] in q["consumption"]       # the monthly flag replaced per_day and operating_days


def test_format_json_and_out_dir(capsys, tmp_path):
    rc, out, err = run(capsys, "estimate", "--storage-size", "1", "--storage-unit", "TiB", "--format", "json", "--out-dir", str(tmp_path / "o"))
    assert rc == 0 and json.loads(out)["label"] == "ESTIMATED FUTURE COST"
    assert (tmp_path / "o" / "estimate.md").exists() and (tmp_path / "o" / "estimate.json").exists() and "wrote" in err


def test_the_region_flag_selects_regional_prices(capsys):
    rc, out, err = run(capsys, "estimate", "--region", "us", "--storage-size", "1", "--storage-unit", "TiB")
    assert rc == 0 and "Pricing region: **us**" in out


# ---------------------------------------------------------------- errors: friendly message, exit code 2, no traceback

@pytest.mark.parametrize("argv, fragment", [
    (["estimate"], "nothing to estimate"),
    (["estimate", "--storage-size", "-5", "--storage-unit", "GB"], "must not be negative"),
    (["estimate", "--storage-size", "5", "--storage-unit", "GBs"], "unknown unit"),
    (["estimate", "--queries-per-day", "10", "--queries-per-month", "300", "--query-size", "1"], "exactly one"),
    (["estimate", "--queries-per-day", "10"], "avg_data_per_query is required"),
    (["estimate", "--enterprise"], "required when Enterprise Edition is enabled"),
    (["estimate", "--enterprise", "--enterprise-slots", "0", "--enterprise-hours-per-day", "1", "--enterprise-days-per-month", "1"], "greater than zero"),
    (["estimate", "--enterprise", "--enterprise-slots", "5", "--enterprise-hours-per-day", "25", "--enterprise-days-per-month", "1"], "24 hours"),
    (["estimate", "--bi-engine", "--bi-capacity", "10", "--bi-unit", "GiB", "--bi-hours-per-day", "1", "--bi-days-per-month", "40"], "31 days"),
])
def test_invalid_inputs_exit_with_a_clear_message(capsys, argv, fragment):
    rc, out, err = run(capsys, *argv)
    assert rc == 2 and out == "" and err.startswith("error:") and fragment in err and "Traceback" not in err


def test_an_unreadable_or_invalid_config_file_is_reported(capsys, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert "not valid JSON" in run(capsys, "estimate", "--config", str(bad))[2]
    assert "cannot read" in run(capsys, "estimate", "--config", str(tmp_path / "missing.json"))[2]
    arr = tmp_path / "arr.json"
    arr.write_text("[1]", encoding="utf-8")
    assert "JSON object" in run(capsys, "estimate", "--config", str(arr))[2]


def test_api_failure_is_reported_without_a_traceback_or_the_key(capsys, monkeypatch):
    def broken(url):
        raise RuntimeError("503 from server using SECRET777")
    monkeypatch.setattr(main, "make_client", lambda: CatalogClient(fetch=broken, api_key="SECRET777", environ={}))
    rc, out, err = run(capsys, "estimate", "--storage-size", "1", "--storage-unit", "TiB")
    assert rc == 2 and err.startswith("error:") and "503" in err and "SECRET777" not in err and "Traceback" not in err


def test_unavailable_regional_pricing_is_reported(capsys):
    rc, _, err = run(capsys, "estimate", "--region", "asia-south1", "--storage-size", "1", "--storage-unit", "TiB")
    assert rc == 2 and "asia-south1" in err and "regions priced for it" in err


def test_a_component_without_a_price_fails_only_when_requested(capsys):
    rc, _, _ = run(capsys, "estimate", "--region", "europe-north1", "--storage-size", "1", "--storage-unit", "TiB")
    assert rc == 2                                                                  # even storage has no price in this fixture region: reported, not guessed


# ---------------------------------------------------------------- prices command

def test_prices_command_lists_the_retrieved_rates(capsys, book):
    rc, out, _ = run(capsys, "prices")
    assert rc == 0 and "Region us-central1" in out and "Public list prices" in out
    for key in ("storage_active_logical", "storage_active_physical", "analysis", "edition_ENTERPRISE", "bi_engine"):
        assert key in out and book.get(key).sku_id in out


def test_prices_command_reports_errors(capsys):
    rc, _, err = run(capsys, "prices", "--region", "asia-south1")
    assert rc == 2 and err.startswith("error:")


def test_tables_per_query_flag_raises_the_minimum(capsys):
    one = json.loads(run(capsys, "estimate", "--queries-per-month", "1000000", "--query-size", "1", "--query-unit", "MiB", "--format", "json")[1])
    three = json.loads(run(capsys, "estimate", "--queries-per-month", "1000000", "--query-size", "1", "--query-unit", "MiB", "--tables-per-query", "3", "--format", "json")[1])
    assert three["total"]["monthly"] > one["total"]["monthly"]


@pytest.mark.parametrize("argv, fragment", [
    (["estimate", "--storage-size", "5"], "storage.unit is required"),
    (["estimate", "--queries-per-month", "10", "--query-size", "5"], "queries.unit is required"),
    (["estimate", "--bi-engine", "--bi-capacity", "10", "--bi-hours-per-day", "1", "--bi-days-per-month", "1"], "bi_engine.unit is required"),
    (["estimate", "--queries-per-month", "10", "--query-size", "5", "--query-unit", "GB", "--tables-per-query", "0"], "greater than zero"),
    (["estimate", "--queries-per-month", "10", "--query-size", "5", "--query-unit", "GB", "--tables-per-query", "2.5"], "whole number"),
])
def test_a_missing_unit_or_bad_table_count_is_rejected(capsys, argv, fragment):
    rc, out, err = run(capsys, *argv)
    assert rc == 2 and fragment in err and out == ""
