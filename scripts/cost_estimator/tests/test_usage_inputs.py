import math

import pytest

from config import GIB, MIB, TIB
from usage_inputs import InputError, parse_inputs, to_bytes


# ---------------------------------------------------------------- unit conversion

def test_decimal_and_binary_units_differ():
    assert to_bytes(1, "GB", "x") == 10 ** 9 and to_bytes(1, "GiB", "x") == 2 ** 30
    assert to_bytes(1, "TB", "x") == 10 ** 12 and to_bytes(1, "TiB", "x") == 2 ** 40
    assert to_bytes(5, "MB", "x") == 5 * 10 ** 6 and to_bytes(5, "MiB", "x") == 5 * MIB


def test_units_are_case_insensitive_and_trimmed():
    assert to_bytes(2, " gib ", "x") == 2 * GIB and to_bytes(2, "Tb", "x") == 2 * 10 ** 12


def test_unknown_unit_is_rejected_and_lists_the_choices():
    with pytest.raises(InputError, match="unknown unit 'GBs'.*TiB"):
        to_bytes(1, "GBs", "storage.size")
    with pytest.raises(InputError):
        to_bytes(1, None, "storage.size")


@pytest.mark.parametrize("bad", [-1, -0.001, float("nan"), float("inf"), "5", None, True])
def test_bad_numbers_are_rejected(bad):
    with pytest.raises(InputError):
        to_bytes(bad, "GB", "storage.size")


# ---------------------------------------------------------------- storage

def test_storage_parses_size_duration_and_model():
    u = parse_inputs({"storage": {"size": 5, "unit": "TB", "duration_months": 3, "billing_model": "Physical", "free_gib_already_used": 2}})
    s = u.storage
    assert s.size_bytes == 5 * 10 ** 12 and s.duration_months == 3 and s.billing_model == "PHYSICAL" and s.free_gib_already_used == 2
    assert u.queries is None and u.enterprise is None and u.bi_engine is None
    assert u.price_keys() == ["storage_active_physical"]


def test_units_are_required_so_gb_and_gib_are_never_confused():
    with pytest.raises(InputError, match="storage.unit is required"):
        parse_inputs({"storage": {"size": 100}})
    with pytest.raises(InputError, match="queries.unit is required"):
        parse_inputs({"queries": {"per_month": 1, "avg_data_per_query": 1}})
    with pytest.raises(InputError, match="bi_engine.unit is required"):
        parse_inputs({"bi_engine": {"capacity": 1, "hours_per_day": 1, "days_per_month": 1}})


def test_storage_defaults():
    s = parse_inputs({"storage": {"size": 100, "unit": "GB"}}).storage
    assert s.size_bytes == 100 * 10 ** 9 and s.duration_months == 1.0 and s.billing_model == "LOGICAL"


def test_storage_requires_a_size_and_a_valid_model_and_positive_duration():
    for bad in [{}, {"size": 1, "billing_model": "compressed"}, {"size": 1, "duration_months": 0}, {"size": -5, "unit": "GB"}, {"size": 1, "free_gib_already_used": -1}]:
        with pytest.raises(InputError):
            parse_inputs({"storage": bad})


def test_zero_storage_is_allowed():
    assert parse_inputs({"storage": {"size": 0, "unit": "GB"}}).storage.size_bytes == 0


# ---------------------------------------------------------------- queries

def test_queries_per_day_times_operating_days():
    q = parse_inputs({"queries": {"per_day": 200, "operating_days": 22, "avg_data_per_query": 50, "unit": "GB"}}).queries
    assert q.queries_per_month == 4400 and q.avg_bytes_per_query == 50 * 10 ** 9
    assert "200 queries a day x 22 operating days" in q.basis_text


def test_operating_days_default_to_30_with_per_day():
    assert parse_inputs({"queries": {"per_day": 10, "avg_data_per_query": 1, "unit": "GB"}}).queries.queries_per_month == 300


def test_queries_per_month_is_taken_as_given():
    assert parse_inputs({"queries": {"per_month": 12345, "avg_data_per_query": 1, "unit": "MiB"}}).queries.queries_per_month == 12345


def test_per_day_and_per_month_are_mutually_exclusive_and_one_is_required():
    with pytest.raises(InputError, match="exactly one"):
        parse_inputs({"queries": {"per_day": 1, "per_month": 30, "avg_data_per_query": 1, "unit": "GB"}})
    with pytest.raises(InputError, match="exactly one"):
        parse_inputs({"queries": {"avg_data_per_query": 1, "unit": "GB"}})


def test_operating_days_only_goes_with_per_day():
    with pytest.raises(InputError, match="only used with per_day"):
        parse_inputs({"queries": {"per_month": 100, "operating_days": 20, "avg_data_per_query": 1, "unit": "GB"}})


def test_query_size_is_required_and_days_are_bounded():
    for bad in [{"per_day": 1}, {"per_day": 1, "operating_days": 32, "avg_data_per_query": 1, "unit": "GB"}, {"per_day": 1, "operating_days": 0, "avg_data_per_query": 1, "unit": "GB"},
                {"per_day": -1, "avg_data_per_query": 1, "unit": "GB"}, {"per_day": 1, "avg_data_per_query": -1, "unit": "GB"}]:
        with pytest.raises(InputError):
            parse_inputs({"queries": bad})


# ---------------------------------------------------------------- optional components

def test_enterprise_and_bi_engine_are_off_unless_given_and_enabled():
    u = parse_inputs({"storage": {"size": 1, "unit": "GB"}})
    assert u.enterprise is None and u.bi_engine is None and "edition_ENTERPRISE" not in u.price_keys() and "bi_engine" not in u.price_keys()
    u = parse_inputs({"storage": {"size": 1, "unit": "GB"}, "enterprise": {"enabled": False}, "bi_engine": {"enabled": False, "capacity": 10}})
    assert u.enterprise is None and u.bi_engine is None


def test_enterprise_parses_and_defaults_to_baseline():
    e = parse_inputs({"enterprise": {"slots": 100, "hours_per_day": 8, "days_per_month": 22}}).enterprise
    assert (e.slots, e.mode, e.hours_per_day, e.days_per_month, e.autoscale_utilization) == (100, "baseline", 8, 22, 1.0)
    e = parse_inputs({"enterprise": {"slots": 100, "mode": "AUTOSCALE", "hours_per_day": 8, "days_per_month": 22, "autoscale_utilization": 0.5}}).enterprise
    assert e.mode == "autoscale" and e.autoscale_utilization == 0.5


def test_enterprise_validation():
    base = {"slots": 100, "hours_per_day": 8, "days_per_month": 22}
    for change in [{"slots": 0}, {"slots": -50}, {"hours_per_day": 25}, {"hours_per_day": 0}, {"days_per_month": 32}, {"mode": "burst"},
                   {"mode": "autoscale", "autoscale_utilization": 1.5}, {"mode": "autoscale", "autoscale_utilization": 0}, {"autoscale_utilization": 0.5}]:
        with pytest.raises(InputError):
            parse_inputs({"enterprise": {**base, **change}})
    for missing in base:
        with pytest.raises(InputError, match="required"):
            parse_inputs({"enterprise": {k: v for k, v in base.items() if k != missing}})


def test_bi_engine_parses_units():
    b = parse_inputs({"bi_engine": {"capacity": 10, "unit": "GiB", "hours_per_day": 8, "days_per_month": 22}}).bi_engine
    assert b.capacity_bytes == 10 * GIB
    b = parse_inputs({"bi_engine": {"capacity": 10, "unit": "GB", "hours_per_day": 8, "days_per_month": 22}}).bi_engine
    assert b.capacity_bytes == 10 * 10 ** 9


def test_bi_engine_validation():
    base = {"capacity": 10, "unit": "GiB", "hours_per_day": 8, "days_per_month": 22}
    for change in [{"capacity": 0}, {"capacity": -1}, {"hours_per_day": 24.5}, {"days_per_month": 40}, {"unit": "bits"}]:
        with pytest.raises(InputError):
            parse_inputs({"bi_engine": {**base, **change}})


# ---------------------------------------------------------------- whole input

def test_nothing_to_estimate_is_an_error():
    for raw in [{}, {"region": "us-central1"}, {"enterprise": {"enabled": False}}]:
        with pytest.raises(InputError, match="nothing to estimate"):
            parse_inputs(raw)


def test_unknown_fields_are_rejected_to_catch_typos():
    with pytest.raises(InputError, match="unknown field"):
        parse_inputs({"storage": {"size": 1, "sizee": 2}})
    with pytest.raises(InputError, match="unknown field"):
        parse_inputs({"storages": {"size": 1, "unit": "GB"}})


def test_region_defaults_and_is_normalised():
    assert parse_inputs({"storage": {"size": 1, "unit": "GB"}}).region == "us-central1"
    assert parse_inputs({"region": " US-East1 ", "storage": {"size": 1, "unit": "GB"}}).region == "us-east1"
    with pytest.raises(InputError):
        parse_inputs({"region": "", "storage": {"size": 1, "unit": "GB"}})


def test_enabled_must_be_a_boolean():
    with pytest.raises(InputError, match="true or false"):
        parse_inputs({"enterprise": {"enabled": "yes", "slots": 1, "hours_per_day": 1, "days_per_month": 1}})


def test_only_requested_components_need_prices():
    u = parse_inputs({"storage": {"size": 1, "unit": "GB"}, "queries": {"per_month": 1, "avg_data_per_query": 1, "unit": "GB"}, "bi_engine": {"capacity": 1, "unit": "GiB", "hours_per_day": 1, "days_per_month": 1}})
    assert u.price_keys() == ["storage_active_logical", "analysis", "bi_engine"]


def test_tables_per_query_is_a_positive_whole_number_defaulting_to_one():
    q = {"per_month": 10, "avg_data_per_query": 1, "unit": "MiB"}
    assert parse_inputs({"queries": q}).queries.tables_per_query == 1
    assert parse_inputs({"queries": dict(q, tables_per_query=3)}).queries.tables_per_query == 3
    assert parse_inputs({"queries": dict(q, tables_per_query=3.0)}).queries.tables_per_query == 3
    for bad in (0, -1, 2.5, "3", True):
        with pytest.raises(InputError):
            parse_inputs({"queries": dict(q, tables_per_query=bad)})


def test_operating_days_defaulting_is_recorded():
    assert parse_inputs({"queries": {"per_day": 5, "avg_data_per_query": 1, "unit": "GB"}}).queries.days_defaulted is True
    assert parse_inputs({"queries": {"per_day": 5, "operating_days": 20, "avg_data_per_query": 1, "unit": "GB"}}).queries.days_defaulted is False
    assert parse_inputs({"queries": {"per_month": 5, "avg_data_per_query": 1, "unit": "GB"}}).queries.days_defaulted is False


def test_a_bad_number_is_reported_before_a_bad_unit():
    with pytest.raises(InputError, match="must not be negative"):
        to_bytes(-5, "GBs", "storage.size")


def test_streaming_and_storage_api_inputs_parse_and_need_units():
    u = parse_inputs({"streaming": {"size_per_month": 5, "unit": "GiB"}, "storage_api": {"size_per_month": 1, "unit": "TiB", "free_gib_already_used": 3}})
    assert u.streaming.size_bytes == 5 * 2 ** 30 and u.storage_api.free_gib_already_used == 3
    assert u.price_keys() == ["streaming_insert", "storage_api_write"]
    with pytest.raises(InputError, match="unit is required"):
        parse_inputs({"streaming": {"size_per_month": 5}})
    with pytest.raises(InputError, match="unknown field"):
        parse_inputs({"streaming": {"size_per_month": 5, "unit": "GiB", "free_gib_already_used": 1}})
