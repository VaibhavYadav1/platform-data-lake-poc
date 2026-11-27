import dataclasses

import pytest

import cost_calculator as cc
from config import GIB, HOURS_PER_MONTH, MIB, TIB
from pricing_api import PriceBook, PricingError
from usage_inputs import parse_inputs


def est(book, **sections):
    return cc.estimate_future(book, parse_inputs(sections))


def comp(e, key):
    return next(c for c in e.components if c.key == key)


# ---------------------------------------------------------------- storage

def gm(book, gib, held=1.0, key="storage_active_logical"):
    """GiB-months billed for `gib` GiB held for `held` of an average 730-hour month, using the catalog's own unit definition."""
    p = book.get(key)
    return gib * held * HOURS_PER_MONTH * 3600 * GIB / p.base_unit_factor


def test_the_catalog_defines_a_storage_month_as_721_hours_and_that_is_applied(book):
    p = book.get("storage_active_logical")
    assert p.base_unit == "By.s" and p.base_unit_factor / GIB / 3600 == pytest.approx(721)
    assert gm(book, 1) == pytest.approx(730 / 721)                                      # a GiB held for an average month is 1.0125 GiB-months
    assert 12 * gm(book, 1) == pytest.approx(8760 / 721)                                # a year (8,760 hours) is 12.15 GiB-months per GiB


def test_storage_cost_is_billable_gib_months_times_the_rate(book):
    rate = book.get("storage_active_logical").list_unit_price
    c = comp(est(book, storage={"size": 5, "unit": "TiB"}), "storage")
    assert c.monthly_cost == pytest.approx((gm(book, 5 * 1024) - 10) * rate)            # 10 GiB-months are free
    assert c.annual_cost == pytest.approx(c.monthly_cost * 12)
    assert any("721 hours" in n for n in c.notes)


def test_decimal_terabytes_are_converted_to_gib_before_pricing(book):
    rate = book.get("storage_active_logical").list_unit_price
    gib = 5 * 10 ** 12 / GIB                                                              # 5 TB (decimal) = 4656.6 GiB
    assert comp(est(book, storage={"size": 5, "unit": "TB"}), "storage").monthly_cost == pytest.approx((gm(book, gib) - 10) * rate)


def test_storage_inside_the_free_tier_costs_nothing(book):
    c = comp(est(book, storage={"size": 8, "unit": "GiB"}), "storage")
    assert c.monthly_cost == 0.0 and any("free tier" in s for s in c.calculation)


def test_the_month_conversion_moves_the_free_tier_boundary(book):
    rate = book.get("storage_active_logical").list_unit_price
    # 9.9 GiB looks free, but held for a month it is 10.02 GiB-months, so the last 0.02 is billed
    assert comp(est(book, storage={"size": 9.9, "unit": "GiB"}), "storage").monthly_cost == pytest.approx((gm(book, 9.9) - 10) * rate)
    assert gm(book, 9.9) > 10


def test_free_storage_used_elsewhere_on_the_account_is_not_available_again(book):
    rate = book.get("storage_active_logical").list_unit_price
    c = comp(est(book, storage={"size": 8, "unit": "GiB", "free_gib_already_used": 5}), "storage")
    assert c.monthly_cost == pytest.approx((gm(book, 8) - 5) * rate)                      # only 5 free GiB-months were left


def test_a_part_month_is_prorated_and_a_long_duration_keeps_the_monthly_rate(book):
    rate = book.get("storage_active_logical").list_unit_price
    half = comp(est(book, storage={"size": 100, "unit": "GiB", "duration_months": 0.5}), "storage")
    assert half.monthly_cost == pytest.approx((gm(book, 100, 0.5) - 10) * rate)
    three = comp(est(book, storage={"size": 100, "unit": "GiB", "duration_months": 3}), "storage")
    assert three.monthly_cost == pytest.approx((gm(book, 100) - 10) * rate)
    assert any("over the whole duration" in s for s in three.calculation)


def test_physical_billing_uses_the_physical_rate(book):
    phys, logical = book.get("storage_active_physical"), book.get("storage_active_logical")
    assert phys.list_unit_price != logical.list_unit_price
    c = comp(est(book, storage={"size": 100, "unit": "GiB", "billing_model": "physical"}), "storage")
    assert c.monthly_cost == pytest.approx((gm(book, 100, key="storage_active_physical") - 10) * phys.list_unit_price) and c.rate_keys == ["storage_active_physical"]


# ---------------------------------------------------------------- on-demand queries

def test_on_demand_cost_is_monthly_billed_tib_times_the_rate_after_the_free_tib(book):
    rate = book.get("analysis").list_unit_price
    c = comp(est(book, queries={"per_day": 200, "operating_days": 22, "avg_data_per_query": 50, "unit": "GiB"}), "on_demand")
    tib = 200 * 22 * 50 / 1024
    assert c.monthly_cost == pytest.approx((tib - 1) * rate)
    assert any("4,400 queries" in s for s in c.calculation)


def test_queries_per_month_gives_the_same_result(book):
    a = comp(est(book, queries={"per_day": 100, "operating_days": 30, "avg_data_per_query": 1, "unit": "GiB"}), "on_demand")
    b = comp(est(book, queries={"per_month": 3000, "avg_data_per_query": 1, "unit": "GiB"}), "on_demand")
    assert a.monthly_cost == pytest.approx(b.monthly_cost)


def test_the_10_mib_per_query_minimum_is_applied(book):
    rate = book.get("analysis").list_unit_price
    c = comp(est(book, queries={"per_month": 1_000_000, "avg_data_per_query": 1, "unit": "MiB"}), "on_demand")
    assert c.monthly_cost == pytest.approx((1_000_000 * 10 * MIB / TIB - 1) * rate)   # each query billed 10 MiB, not 1
    assert any("10 MiB minimum applies per query and per referenced table" in n for n in c.notes)


def test_the_minimum_also_applies_per_referenced_table(book):
    rate = book.get("analysis").list_unit_price
    one = comp(est(book, queries={"per_month": 1_000_000, "avg_data_per_query": 1, "unit": "MiB"}), "on_demand")
    three = comp(est(book, queries={"per_month": 1_000_000, "avg_data_per_query": 1, "unit": "MiB", "tables_per_query": 3}), "on_demand")
    assert three.monthly_cost == pytest.approx((1_000_000 * 30 * MIB / TIB - 1) * rate)         # three tables: at least 30 MiB a query
    assert three.monthly_cost > one.monthly_cost
    assert ("Tables referenced per query", "3") in three.consumption


def test_the_table_minimum_does_not_change_queries_already_larger_than_it(book):
    q = {"per_month": 1000, "avg_data_per_query": 5, "unit": "GiB"}
    assert comp(est(book, queries=dict(q, tables_per_query=4)), "on_demand").monthly_cost == comp(est(book, queries=q), "on_demand").monthly_cost


def test_defaulted_operating_days_are_called_out(book):
    c = comp(est(book, queries={"per_day": 10, "avg_data_per_query": 1, "unit": "GiB"}), "on_demand")
    assert any("30 days a month was assumed" in n for n in c.notes)
    c = comp(est(book, queries={"per_day": 10, "operating_days": 22, "avg_data_per_query": 1, "unit": "GiB"}), "on_demand")
    assert not any("was assumed" in n for n in c.notes)


def test_per_query_size_is_rounded_up_to_a_mib(book):
    c = comp(est(book, queries={"per_month": 1_000_000, "avg_data_per_query": 10 * MIB + 1, "unit": "B"}), "on_demand")
    assert c.monthly_cost == pytest.approx((1_000_000 * 11 * MIB / TIB - 1) * book.get("analysis").list_unit_price)


def test_free_query_tib_used_elsewhere_reduces_the_allowance(book):
    rate = book.get("analysis").list_unit_price
    c = comp(est(book, queries={"per_month": 512, "avg_data_per_query": 1, "unit": "GiB", "free_tib_already_used": 0.8}), "on_demand")
    assert c.monthly_cost == pytest.approx((0.5 - 0.2) * rate)


def test_queries_inside_the_free_tib_cost_nothing(book):
    assert comp(est(book, queries={"per_month": 100, "avg_data_per_query": 5, "unit": "GiB"}), "on_demand").monthly_cost == 0.0


def test_zero_queries_is_a_zero_cost_not_an_error(book):
    c = comp(est(book, queries={"per_month": 0, "avg_data_per_query": 5, "unit": "GiB"}), "on_demand")
    assert c.requested and c.monthly_cost == 0.0


# ---------------------------------------------------------------- free tier and annual rules

def test_annual_cost_is_twelve_months_not_one_free_tier_a_year(book):
    rate = book.get("analysis").list_unit_price
    c = comp(est(book, queries={"per_month": 1536, "avg_data_per_query": 1, "unit": "GiB"}), "on_demand")      # 1.5 TiB a month
    assert c.monthly_cost == pytest.approx(0.5 * rate)
    assert c.annual_cost == pytest.approx(6 * rate)                                   # not (18 - 1) x rate
    inside = comp(est(book, queries={"per_month": 900, "avg_data_per_query": 1, "unit": "GiB"}), "on_demand")
    assert inside.monthly_cost == 0.0 and inside.annual_cost == 0.0


def test_each_free_tier_is_applied_once_to_its_own_sku_and_never_shared(book):
    # 8 GiB of storage is free storage; 0.5 TiB of queries is free query volume: neither uses the other's allowance
    e = est(book, storage={"size": 8, "unit": "GiB"}, queries={"per_month": 512, "avg_data_per_query": 1, "unit": "GiB"})
    assert e.monthly_total == 0.0
    over = est(book, storage={"size": 18, "unit": "GiB"}, queries={"per_month": 1536, "avg_data_per_query": 1, "unit": "GiB"})
    s, q = book.get("storage_active_logical").list_unit_price, book.get("analysis").list_unit_price
    assert over.monthly_total == pytest.approx((gm(book, 18) - 10) * s + 0.5 * q)


# ---------------------------------------------------------------- Enterprise Edition

def test_enterprise_baseline_is_slots_times_hours_times_the_rate(book):
    rate = book.get("edition_ENTERPRISE").list_unit_price
    c = comp(est(book, enterprise={"slots": 100, "hours_per_day": 8, "days_per_month": 22}), "enterprise")
    assert c.monthly_cost == pytest.approx(100 * 8 * 22 * rate)
    assert ("Slot-hours per month", "17,600.00") in c.consumption


def test_enterprise_autoscale_rounds_slots_up_to_multiples_of_50(book):
    rate = book.get("edition_ENTERPRISE").list_unit_price
    c = comp(est(book, enterprise={"slots": 120, "mode": "autoscale", "hours_per_day": 4, "days_per_month": 10}), "enterprise")
    assert c.monthly_cost == pytest.approx(150 * 4 * 10 * rate)
    assert any("rounded up" in w for w in c.warnings)
    assert any("rounded up" in w for w in est(book, enterprise={"slots": 120, "mode": "autoscale", "hours_per_day": 4, "days_per_month": 10}).warnings)


def test_no_warning_when_nothing_needs_attention(book):
    # regression: the general autoscale note mentions rounding, but 100 slots is already a multiple of 50, so there is nothing to warn about
    e = est(book, storage={"size": 1, "unit": "TiB"}, enterprise={"slots": 100, "mode": "autoscale", "hours_per_day": 8, "days_per_month": 22},
            bi_engine={"capacity": 10, "unit": "GiB", "hours_per_day": 8, "days_per_month": 22})
    assert e.warnings == []


def test_enterprise_autoscale_utilization_scales_the_charged_time(book):
    rate = book.get("edition_ENTERPRISE").list_unit_price
    c = comp(est(book, enterprise={"slots": 100, "mode": "autoscale", "hours_per_day": 8, "days_per_month": 22, "autoscale_utilization": 0.25}), "enterprise")
    assert c.monthly_cost == pytest.approx(100 * 0.25 * 8 * 22 * rate)


def test_enterprise_baseline_slots_are_also_rounded_up_to_multiples_of_50_with_a_warning(book):
    rate = book.get("edition_ENTERPRISE").list_unit_price
    e = est(book, enterprise={"slots": 120, "hours_per_day": 1, "days_per_month": 1})
    assert comp(e, "enterprise").monthly_cost == pytest.approx(150 * rate)              # baseline can only be configured in multiples of 50
    assert any("120 slots requested were rounded up to 150" in w and "baseline slots can only be configured" in w for w in e.warnings)
    assert est(book, enterprise={"slots": 100, "hours_per_day": 1, "days_per_month": 1}).warnings == []


def test_baseline_is_not_discounted_by_utilization(book):
    rate = book.get("edition_ENTERPRISE").list_unit_price
    assert comp(est(book, enterprise={"slots": 100, "hours_per_day": 2, "days_per_month": 3}), "enterprise").monthly_cost == pytest.approx(100 * 2 * 3 * rate)


def test_enterprise_notes_state_the_billing_rules(book):
    c = comp(est(book, enterprise={"slots": 100, "mode": "autoscale", "hours_per_day": 8, "days_per_month": 22}), "enterprise")
    text = " ".join(c.notes)
    assert "one-minute minimum" in text and "multiples of 50" in text and "commitments" in text and "per second" in text


# ---------------------------------------------------------------- BI Engine

def test_bi_engine_cost_is_gib_hours_times_the_rate(book):
    rate = book.get("bi_engine").list_unit_price
    c = comp(est(book, bi_engine={"capacity": 10, "unit": "GiB", "hours_per_day": 8, "days_per_month": 22}), "bi_engine")
    assert c.monthly_cost == pytest.approx(10 * 8 * 22 * rate)


def test_bi_engine_decimal_gb_is_converted_to_gib(book):
    rate = book.get("bi_engine").list_unit_price
    c = comp(est(book, bi_engine={"capacity": 10, "unit": "GB", "hours_per_day": 1, "days_per_month": 1}), "bi_engine")
    assert c.monthly_cost == pytest.approx(10 * 10 ** 9 / GIB * rate)


def test_bi_engine_outside_the_documented_range_is_flagged_not_rejected(book):
    big = est(book, bi_engine={"capacity": 300, "unit": "GiB", "hours_per_day": 1, "days_per_month": 1})
    assert comp(big, "bi_engine").monthly_cost > 0 and any("outside the documented" in w for w in big.warnings)
    assert not est(book, bi_engine={"capacity": 10, "unit": "GiB", "hours_per_day": 1, "days_per_month": 1}).warnings


# ---------------------------------------------------------------- optional components and totals

def test_disabled_components_are_not_requested_and_not_counted(book):
    e = est(book, storage={"size": 5, "unit": "TiB"})
    assert [c.requested for c in e.components] == [True, False, False, False, False, False]
    assert comp(e, "enterprise").monthly_cost is None and comp(e, "bi_engine").annual_cost is None
    assert e.monthly_total == comp(e, "storage").monthly_cost


def test_totals_add_the_requested_components_and_annual_is_twelve_times_monthly(book):
    e = est(book, storage={"size": 5, "unit": "TiB"}, queries={"per_day": 200, "operating_days": 22, "avg_data_per_query": 50, "unit": "GiB"},
            enterprise={"slots": 100, "mode": "autoscale", "hours_per_day": 8, "days_per_month": 22},
            bi_engine={"capacity": 10, "unit": "GiB", "hours_per_day": 8, "days_per_month": 22})
    parts = [comp(e, k).monthly_cost for k in ("storage", "on_demand", "enterprise", "bi_engine")]
    assert all(p is not None for p in parts)
    assert e.monthly_total == pytest.approx(sum(parts)) and e.annual_total == pytest.approx(12 * e.monthly_total)
    assert e.currency == "USD" and e.region == "us-central1" and e.prices_fetched_at == book.fetched_at


def test_the_estimate_records_its_assumptions(book):
    e = est(book, storage={"size": 1, "unit": "TiB"})
    text = " ".join(e.assumptions)
    assert "public list prices" in text and "12 x the monthly cost" in text and "user's expectations" in text
    assert "account-wide" in text and "per project" in text and "free_*_already_used" in text


# ---------------------------------------------------------------- guard against a changed billing unit

def test_a_changed_catalog_unit_is_an_error_not_a_wrong_price(book):
    bad = dataclasses.replace(book.get("analysis"), usage_unit="GiBy")
    prices = dict(book.prices, analysis=bad)
    with pytest.raises(PricingError, match="billing unit"):
        cc.estimate_future(PriceBook(prices, book.region, book.fetched_at), parse_inputs({"queries": {"per_month": 1, "avg_data_per_query": 1, "unit": "GB"}}))


def test_bi_engine_notes_say_what_is_and_is_not_known(book):
    c = comp(est(book, bi_engine={"capacity": 10, "unit": "GiB", "hours_per_day": 1, "days_per_month": 1}), "bi_engine")
    text = " ".join(c.notes)
    assert "upper bound" in text and "could not be retrieved" in text and "not counted toward slot reservations" in text


def test_bi_engine_does_not_change_the_on_demand_or_enterprise_lines(book):
    base = {"queries": {"per_month": 1536, "avg_data_per_query": 1, "unit": "GiB"}, "enterprise": {"slots": 100, "hours_per_day": 8, "days_per_month": 22}}
    without = est(book, **base)
    with_bi = est(book, **base, bi_engine={"capacity": 10, "unit": "GiB", "hours_per_day": 8, "days_per_month": 22})
    for key in ("on_demand", "enterprise"):
        assert comp(with_bi, key).monthly_cost == comp(without, key).monthly_cost
    assert with_bi.monthly_total == pytest.approx(without.monthly_total + comp(with_bi, "bi_engine").monthly_cost)


# ---------------------------------------------------------------- streaming inserts and Storage Write API

def test_streaming_inserts_are_priced_per_mib_with_no_free_tier(book):
    rate = book.get("streaming_insert").list_unit_price
    assert rate == pytest.approx(0.00005)
    e = est(book, streaming={"size_per_month": 20.29, "unit": "MiB"})
    c = comp(e, "streaming")
    assert c.monthly_cost == pytest.approx(20.29 * rate) and c.annual_cost == pytest.approx(20.29 * rate * 12)
    assert e.monthly_total == c.monthly_cost


def test_streaming_decimal_units_are_converted_to_mib(book):
    rate = book.get("streaming_insert").list_unit_price
    assert comp(est(book, streaming={"size_per_month": 1, "unit": "GB"}), "streaming").monthly_cost == pytest.approx(10 ** 9 / MIB * rate)


def test_storage_api_write_first_2_tib_a_month_are_free(book):
    assert comp(est(book, storage_api={"size_per_month": 2, "unit": "TiB"}), "storage_api").monthly_cost == 0.0
    rate = book.get("storage_api_write").list_unit_price
    assert rate == pytest.approx(0.025)
    assert comp(est(book, storage_api={"size_per_month": 3, "unit": "TiB"}), "storage_api").monthly_cost == pytest.approx(1024 * rate)


def test_storage_api_free_tier_used_elsewhere_is_not_available_again(book):
    rate = book.get("storage_api_write").list_unit_price
    c = comp(est(book, storage_api={"size_per_month": 100, "unit": "GiB", "free_gib_already_used": 2000}), "storage_api")
    assert c.monthly_cost == pytest.approx((2000 + 100 - 2048) * rate)


def test_the_poc_f_window_matches_the_hand_calculation(book):
    # 24-26 Nov 2026: 20.29 MiB streamed, 0.000729 GiB written through the Storage Write API (billing export usage lines)
    e = est(book, streaming={"size_per_month": 20.29, "unit": "MiB"}, storage_api={"size_per_month": 0.000729, "unit": "GiB", "free_gib_already_used": 2048})
    assert comp(e, "streaming").monthly_cost * 95.23 == pytest.approx(0.0966, abs=1e-4)
    assert comp(e, "storage_api").monthly_cost * 95.23 == pytest.approx(0.0017, abs=1e-4)
