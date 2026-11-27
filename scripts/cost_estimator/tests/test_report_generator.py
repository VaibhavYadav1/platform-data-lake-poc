import json
import os

import cost_calculator as cc
import report_generator as rg
from usage_inputs import parse_inputs

FULL = {"storage": {"size": 5, "unit": "TiB"}, "queries": {"per_day": 200, "operating_days": 22, "avg_data_per_query": 50, "unit": "GiB"},
        "enterprise": {"slots": 100, "mode": "autoscale", "hours_per_day": 8, "days_per_month": 22},
        "bi_engine": {"capacity": 10, "unit": "GiB", "hours_per_day": 8, "days_per_month": 22}}


def report_for(book, raw):
    est = cc.estimate_future(book, parse_inputs(raw))
    return rg.build_report(est, book), est


def test_the_report_is_labelled_estimated_future_cost_not_actual_or_historical(book):
    md = rg.render_markdown(report_for(book, FULL)[0])
    assert md.startswith("# Estimated Future Cost: BigQuery")
    assert "**ESTIMATED FUTURE COST.**" in md and "not an actual cost and not a historical cost" in md
    for forbidden in ("Actual billed", "Billing export", "historical usage", "S1", "S2", "S3"):
        assert forbidden not in md


def test_breakdown_table_has_every_component_and_the_totals(book):
    r, est = report_for(book, FULL)
    md = rg.render_markdown(r)
    for name in ("BigQuery Storage", "On-Demand Query Processing", "Enterprise Edition", "BI Engine"):
        assert "| %s |" % name in md
    assert "| **Total Estimated Monthly Cost** | **%s**" % rg.money(est.monthly_total) in md
    assert "Estimated annual cost: **%s**" % rg.money(est.annual_total) in md


def test_components_not_requested_show_n_a_and_get_no_price_row(book):
    r, _ = report_for(book, {"storage": {"size": 5, "unit": "TiB"}})
    md = rg.render_markdown(r)
    assert md.count("N/A (not requested)") == 10                   # five components x monthly and annual
    assert [p["component"] for p in r["prices"]["rates"]] == ["BigQuery Storage"]
    assert "Enterprise Edition" not in md.split("## Pricing rates retrieved")[1].split("## Inputs you provided")[0]


def test_pricing_section_states_region_date_source_and_that_prices_are_list_prices(book):
    r, _ = report_for(book, FULL)
    md = rg.render_markdown(r)
    assert "Pricing region: **us-central1**" in md and "Pricing retrieved: **%s**" % book.fetched_date in md
    assert "public list prices" in md and "negotiated or contract prices are not included" in md
    assert "Cloud Billing Catalog API v1" in md
    for key in ("analysis", "storage_active_logical", "edition_ENTERPRISE", "bi_engine"):
        assert book.get(key).sku_id in md


def test_user_inputs_and_retrieved_prices_are_in_separate_sections(book):
    md = rg.render_markdown(report_for(book, FULL)[0])
    assert md.index("## Pricing rates retrieved from the API") < md.index("## Inputs you provided (your assumptions)")
    inputs = md.split("## Inputs you provided (your assumptions)")[1].split("## Calculation details")[0]
    assert "Expected data stored: 5 TiB" in inputs and "Slot capacity: 100" in inputs and "Capacity: 10 GiB" in inputs
    assert "SKU" not in inputs and "per GiB" not in inputs


def test_consumption_and_calculation_details_are_shown(book):
    md = rg.render_markdown(report_for(book, FULL)[0])
    assert "## Expected resource consumption" in md and "Billed volume per month" in md and "Slot-hours per month" in md and "GiB-hours per month" in md
    assert "## Calculation details" in md and "## Assumptions" in md


def test_json_matches_the_markdown_totals(book):
    r, est = report_for(book, FULL)
    data = json.loads(json.dumps(r))
    assert data["label"] == "ESTIMATED FUTURE COST" and data["total"]["monthly"] == est.monthly_total
    assert data["total"]["annual"] == data["total"]["monthly"] * 12
    assert data["prices"]["kind"] == "public list prices" and data["prices"]["retrieved_date"] == book.fetched_date


def test_outputs_are_written(book, tmp_path):
    r, _ = report_for(book, FULL)
    paths = rg.write_outputs(r, str(tmp_path / "out"))
    assert {os.path.basename(p) for p in paths} == {"estimate.md", "estimate.json"}
    assert json.load(open(paths[1], encoding="utf-8"))["region"] == "us-central1"


def test_money_formatting():
    assert rg.money(1234.5) == "1,234.50 USD" and rg.money(0.0) == "0.00 USD" and rg.money(None) == "N/A (not requested)"


def test_warnings_section_appears_only_when_there_is_a_real_warning(book):
    assert "## Warnings" not in rg.render_markdown(report_for(book, FULL)[0])
    risky = dict(FULL, enterprise={"slots": 120, "mode": "autoscale", "hours_per_day": 8, "days_per_month": 22})
    md = rg.render_markdown(report_for(book, risky)[0])
    assert "## Warnings" in md and "120 slots requested were rounded up to 150" in md
