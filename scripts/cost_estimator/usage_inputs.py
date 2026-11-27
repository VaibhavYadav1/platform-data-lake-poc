"""Expected future usage, as the user states it: parsing, unit conversion and validation.

Every input is a user assumption. Nothing is read from existing projects, jobs or billing.

Accepted shape (JSON file or command-line flags build the same dict):
{
  "region": "us-central1",
  "storage":     {"size": 5, "unit": "TB", "duration_months": 1, "billing_model": "logical", "free_gib_already_used": 0},
  "queries":     {"per_day": 200, "operating_days": 22, "avg_data_per_query": 50, "unit": "GB", "tables_per_query": 1, "free_tib_already_used": 0},
  "enterprise":  {"enabled": true, "slots": 100, "mode": "autoscale", "hours_per_day": 8, "days_per_month": 22, "autoscale_utilization": 1.0},
  "bi_engine":   {"enabled": true, "capacity": 10, "unit": "GiB", "hours_per_day": 8, "days_per_month": 22}
}
A component that is missing, or has "enabled": false, is not estimated. Use "per_month" instead of "per_day" and "operating_days" to give a monthly query count.

Units are REQUIRED wherever a size is given. KB, MB, GB, TB, PB are decimal (powers of 1000); KiB, MiB, GiB, TiB, PiB are binary (powers of 1024). BigQuery bills in GiB and TiB,
so 1 TB (decimal) is 0.909 TiB. Use GiB or TiB to avoid the conversion.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from config import DEFAULT_REGION, MAX_DAYS_PER_MONTH, MAX_HOURS_PER_DAY, UNIT_BYTES, UNIT_NAMES


class InputError(ValueError):
    """The user's inputs are missing, malformed, out of range or in an unknown unit."""


@dataclass(frozen=True)
class StorageInput:
    size_bytes: float
    size_text: str                      # as entered, e.g. "5 TB"
    duration_months: float = 1.0
    billing_model: str = "LOGICAL"      # LOGICAL or PHYSICAL: the size above is in the bytes this model bills
    free_gib_already_used: float = 0.0  # free storage this month already used by other usage on the same billing account


@dataclass(frozen=True)
class QueryInput:
    queries_per_month: float
    avg_bytes_per_query: float
    avg_text: str
    basis_text: str                     # how the monthly count was given
    tables_per_query: int = 1           # tables each query references: the 10 MiB minimum applies per referenced table
    days_defaulted: bool = False        # operating days were not given and defaulted to 30
    free_tib_already_used: float = 0.0  # free query TiB this month already used by other usage on the same billing account


@dataclass(frozen=True)
class EnterpriseInput:
    slots: float
    mode: str                           # "baseline" or "autoscale"
    hours_per_day: float
    days_per_month: float
    autoscale_utilization: float = 1.0  # autoscale mode: share of operating time the slots are scaled up


@dataclass(frozen=True)
class BiEngineInput:
    capacity_bytes: float
    capacity_text: str
    hours_per_day: float
    days_per_month: float


@dataclass(frozen=True)
class IngestInput:
    """Data written per month through legacy streaming inserts or the Storage Write API."""
    size_bytes: float
    size_text: str
    free_gib_already_used: float = 0.0  # Storage Write API only: free GiB this month already used elsewhere on the billing account


@dataclass(frozen=True)
class UsageInputs:
    region: str = DEFAULT_REGION
    storage: StorageInput | None = None
    queries: QueryInput | None = None
    enterprise: EnterpriseInput | None = None
    bi_engine: BiEngineInput | None = None
    streaming: IngestInput | None = None
    storage_api: IngestInput | None = None

    def price_keys(self) -> list:
        """The price-book entries the requested components need. Nothing else is fetched."""
        keys = []
        if self.storage:
            keys.append("storage_active_physical" if self.storage.billing_model == "PHYSICAL" else "storage_active_logical")
        if self.queries:
            keys.append("analysis")
        if self.enterprise:
            keys.append("edition_ENTERPRISE")
        if self.bi_engine:
            keys.append("bi_engine")
        if self.streaming:
            keys.append("streaming_insert")
        if self.storage_api:
            keys.append("storage_api_write")
        return keys


# ---------------------------------------------------------------- field validators

def _number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError("%s must be a number, got %r" % (field, value))
    if not math.isfinite(value):
        raise InputError("%s must be a finite number, got %r" % (field, value))
    return float(value)


def non_negative(value, field: str) -> float:
    v = _number(value, field)
    if v < 0:
        raise InputError("%s must not be negative, got %s" % (field, value))
    return v


def positive(value, field: str) -> float:
    v = _number(value, field)
    if v <= 0:
        raise InputError("%s must be greater than zero, got %s" % (field, value))
    return v


def to_bytes(value, unit, field: str) -> float:
    number = non_negative(value, field)
    if not isinstance(unit, str) or unit.strip().lower() not in UNIT_BYTES:
        raise InputError("%s: unknown unit %r (use one of %s)" % (field, unit, ", ".join(UNIT_NAMES)))
    return number * UNIT_BYTES[unit.strip().lower()]


def _unit(section: dict, name: str) -> str:
    """Units are required: GB and GiB differ by 7%, so a missing unit must not silently become one of them."""
    if "unit" not in section:
        raise InputError("%s.unit is required (for example GiB or TiB for binary, GB or TB for decimal)" % name)
    return section["unit"]


def _hours(value, field: str) -> float:
    v = positive(value, field)
    if v > MAX_HOURS_PER_DAY:
        raise InputError("%s cannot be more than %d hours a day, got %s" % (field, MAX_HOURS_PER_DAY, value))
    return v


def _days(value, field: str) -> float:
    v = positive(value, field)
    if v > MAX_DAYS_PER_MONTH:
        raise InputError("%s cannot be more than %d days a month, got %s" % (field, MAX_DAYS_PER_MONTH, value))
    return v


def _check_keys(section: dict, allowed: set, name: str) -> None:
    if not isinstance(section, dict):
        raise InputError("%s must be an object, got %r" % (name, section))
    unknown = set(section) - allowed
    if unknown:
        raise InputError("%s: unknown field(s) %s (allowed: %s)" % (name, ", ".join(sorted(unknown)), ", ".join(sorted(allowed))))


def _enabled(section: dict) -> bool:
    flag = section.get("enabled", True)
    if not isinstance(flag, bool):
        raise InputError("enabled must be true or false, got %r" % (flag,))
    return flag


def _text(value, unit) -> str:
    return "%g %s" % (value, unit)


# ---------------------------------------------------------------- components

def _storage(s: dict) -> StorageInput | None:
    _check_keys(s, {"enabled", "size", "unit", "duration_months", "billing_model", "free_gib_already_used"}, "storage")
    if not _enabled(s):
        return None
    if "size" not in s:
        raise InputError("storage.size is required")
    unit = _unit(s, "storage")
    model = str(s.get("billing_model", "logical")).strip().upper()
    if model not in ("LOGICAL", "PHYSICAL"):
        raise InputError("storage.billing_model must be logical or physical, got %r" % s.get("billing_model"))
    return StorageInput(to_bytes(s["size"], unit, "storage.size"), _text(s["size"], unit), positive(s.get("duration_months", 1.0), "storage.duration_months"),
                        model, non_negative(s.get("free_gib_already_used", 0.0), "storage.free_gib_already_used"))


def _queries(q: dict) -> QueryInput | None:
    _check_keys(q, {"enabled", "per_day", "per_month", "operating_days", "avg_data_per_query", "unit", "tables_per_query", "free_tib_already_used"}, "queries")
    if not _enabled(q):
        return None
    if ("per_day" in q) == ("per_month" in q):
        raise InputError("queries: give exactly one of per_day or per_month")
    if "avg_data_per_query" not in q:
        raise InputError("queries.avg_data_per_query is required")
    unit = _unit(q, "queries")
    tables = positive(q.get("tables_per_query", 1), "queries.tables_per_query")
    if tables != int(tables):
        raise InputError("queries.tables_per_query must be a whole number, got %s" % q["tables_per_query"])
    defaulted = "per_day" in q and "operating_days" not in q
    if "per_day" in q:
        days = _days(q.get("operating_days", 30), "queries.operating_days")
        per_day = non_negative(q["per_day"], "queries.per_day")
        monthly, basis = per_day * days, "%g queries a day x %g operating days" % (per_day, days)
    else:
        if "operating_days" in q:
            raise InputError("queries.operating_days is only used with per_day")
        monthly = non_negative(q["per_month"], "queries.per_month")
        basis = "%g queries a month" % monthly
    return QueryInput(monthly, to_bytes(q["avg_data_per_query"], unit, "queries.avg_data_per_query"), _text(q["avg_data_per_query"], unit), basis, int(tables),
                      defaulted, non_negative(q.get("free_tib_already_used", 0.0), "queries.free_tib_already_used"))


def _enterprise(e: dict) -> EnterpriseInput | None:
    _check_keys(e, {"enabled", "slots", "mode", "hours_per_day", "days_per_month", "autoscale_utilization"}, "enterprise")
    if not _enabled(e):
        return None
    for req in ("slots", "hours_per_day", "days_per_month"):
        if req not in e:
            raise InputError("enterprise.%s is required when Enterprise Edition is enabled" % req)
    mode = str(e.get("mode", "baseline")).strip().lower()
    if mode not in ("baseline", "autoscale"):
        raise InputError("enterprise.mode must be baseline or autoscale, got %r" % e.get("mode"))
    util = positive(e.get("autoscale_utilization", 1.0), "enterprise.autoscale_utilization")
    if util > 1:
        raise InputError("enterprise.autoscale_utilization must be between 0 and 1, got %s" % util)
    if mode == "baseline" and "autoscale_utilization" in e:
        raise InputError("enterprise.autoscale_utilization only applies to autoscale mode")
    return EnterpriseInput(positive(e["slots"], "enterprise.slots"), mode, _hours(e["hours_per_day"], "enterprise.hours_per_day"),
                           _days(e["days_per_month"], "enterprise.days_per_month"), util)


def _bi_engine(b: dict) -> BiEngineInput | None:
    _check_keys(b, {"enabled", "capacity", "unit", "hours_per_day", "days_per_month"}, "bi_engine")
    if not _enabled(b):
        return None
    for req in ("capacity", "hours_per_day", "days_per_month"):
        if req not in b:
            raise InputError("bi_engine.%s is required when BI Engine is enabled" % req)
    unit = _unit(b, "bi_engine")
    cap = to_bytes(b["capacity"], unit, "bi_engine.capacity")
    if cap <= 0:
        raise InputError("bi_engine.capacity must be greater than zero")
    return BiEngineInput(cap, _text(b["capacity"], unit), _hours(b["hours_per_day"], "bi_engine.hours_per_day"), _days(b["days_per_month"], "bi_engine.days_per_month"))


def _ingest(s: dict, name: str, allow_free: bool) -> IngestInput | None:
    _check_keys(s, {"enabled", "size_per_month", "unit"} | ({"free_gib_already_used"} if allow_free else set()), name)
    if not _enabled(s):
        return None
    if "size_per_month" not in s:
        raise InputError("%s.size_per_month is required" % name)
    unit = _unit(s, name)
    return IngestInput(to_bytes(s["size_per_month"], unit, "%s.size_per_month" % name), _text(s["size_per_month"], unit),
                       non_negative(s.get("free_gib_already_used", 0.0), "%s.free_gib_already_used" % name) if allow_free else 0.0)


def parse_inputs(raw: dict) -> UsageInputs:
    _check_keys(raw, {"region", "storage", "queries", "enterprise", "bi_engine", "streaming", "storage_api"}, "inputs")
    region = raw.get("region", DEFAULT_REGION)
    if not isinstance(region, str) or not region.strip():
        raise InputError("region must be a non-empty string, got %r" % (region,))
    usage = UsageInputs(region=region.strip().lower(),
                        storage=_storage(raw["storage"]) if "storage" in raw else None,
                        queries=_queries(raw["queries"]) if "queries" in raw else None,
                        enterprise=_enterprise(raw["enterprise"]) if "enterprise" in raw else None,
                        bi_engine=_bi_engine(raw["bi_engine"]) if "bi_engine" in raw else None,
                        streaming=_ingest(raw["streaming"], "streaming", False) if "streaming" in raw else None,
                        storage_api=_ingest(raw["storage_api"], "storage_api", True) if "storage_api" in raw else None)
    if not (usage.storage or usage.queries or usage.enterprise or usage.bi_engine or usage.streaming or usage.storage_api):
        raise InputError("nothing to estimate: give storage, queries, enterprise, bi_engine, streaming or storage_api inputs")
    return usage
