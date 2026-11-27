"""Future BigQuery cost, from expected usage and current Catalog API prices. Pure functions: no GCP calls, no prices of their own.

Rules this module follows
  * Quantities are converted to each SKU's own usage unit before a price is applied (the unit and its base-unit factor come from the API).
  * A free tier is applied ONCE per SKU, to the whole monthly quantity, never per input. The catalog marks storage and on-demand analysis
    as ACCOUNT / MONTHLY: the allowance belongs to the billing account and resets every month. Other usage on the account that already
    consumed part of it is passed in by the user (free_*_already_used).
  * Annual cost is 12 x the monthly cost, because the free tiers reset each month; the free tier is not applied once per year.
  * On-demand bills at least 10 MiB per query. Enterprise autoscale bills slots in multiples of 50, rounded up.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from config import AUTOSCALE_STEP_SLOTS, BI_ENGINE_DOCUMENTED_GIB, GIB, HOURS_PER_MONTH, MIB, MIN_BYTES_BILLED_PER_QUERY, MONTHS_PER_YEAR, TIB
from pricing_api import PriceBook, PricingError, SkuPrice
from usage_inputs import BiEngineInput, EnterpriseInput, IngestInput, QueryInput, StorageInput, UsageInputs


def n(x: float, d: int = 2) -> str:
    return "{:,.{d}f}".format(x, d=d)


def _expect_unit(price: SkuPrice, unit: str) -> None:
    if price.usage_unit != unit:
        raise PricingError("%s is priced per %r, expected %r: the catalog changed its billing unit" % (price.description, price.usage_unit, unit))


@dataclass
class Component:
    key: str
    name: str
    requested: bool
    monthly_cost: float | None = None
    consumption: list = field(default_factory=list)    # [(label, text)]
    rate_keys: list = field(default_factory=list)      # price-book keys behind this component
    calculation: list = field(default_factory=list)    # human-readable steps with the numbers
    notes: list = field(default_factory=list)          # how the figure was reached
    warnings: list = field(default_factory=list)       # something about THIS input needs attention

    @property
    def annual_cost(self) -> float | None:
        return None if self.monthly_cost is None else self.monthly_cost * MONTHS_PER_YEAR


@dataclass
class FutureEstimate:
    region: str
    currency: str
    price_source: str
    prices_fetched_at: str
    components: list
    monthly_total: float
    annual_total: float
    usage: UsageInputs
    assumptions: list
    warnings: list


# ---------------------------------------------------------------- components

def estimate_storage(book: PriceBook, s: StorageInput) -> Component:
    key = "storage_active_physical" if s.billing_model == "PHYSICAL" else "storage_active_logical"
    price = book.get(key)
    _expect_unit(price, "GiBy.mo")
    if price.base_unit != "By.s":
        raise PricingError("%s is measured in %r, expected byte-seconds: the catalog changed its billing unit" % (price.description, price.base_unit))
    gib = s.size_bytes / GIB
    held = min(s.duration_months, 1.0)
    # The catalog defines 1 GiB-month as base_unit_factor / 2^30 seconds of holding one GiB (2,595,600 s = 721 hours). An average month has
    # 730 hours, so a GiB held all month is 730 / 721 GiB-months, about 1.2% more than a plain GiB x months figure.
    hours_per_gib_month = price.base_unit_factor / GIB / 3600
    month_factor = HOURS_PER_MONTH / hours_per_gib_month
    gib_months = gib * held * month_factor
    free = max(0.0, min(gib_months, price.free_quantity - s.free_gib_already_used))
    cost = price.tier_cost(gib_months, s.free_gib_already_used)
    c = Component("storage", "BigQuery Storage", True, cost, rate_keys=[key])
    c.consumption = [("Data stored", "%s (= %s GiB, %s billing)" % (s.size_text, n(gib, 4), s.billing_model.lower())),
                     ("Duration", "%s month(s)" % n(s.duration_months, 2)), ("Billable quantity per month", "%s GiB-months" % n(gib_months, 4))]
    c.calculation = ["%s GiB x %s of a %d-hour month / %s hours per GiB-month = %s GiB-months" % (n(gib, 4), n(held, 2), HOURS_PER_MONTH, n(hours_per_gib_month, 0), n(gib_months, 4)),
                     "free tier %s GiB-months per month, %s already used elsewhere on the billing account, %s applied" % (n(price.free_quantity, 2), n(s.free_gib_already_used, 2), n(free, 4)),
                     "(%s - %s) GiB-months x %s %s per GiB-month = %s %s" % (n(gib_months, 4), n(free, 4), price.list_unit_price, price.currency, n(cost, 4), price.currency)]
    if s.duration_months > 1:
        c.calculation.append("held for %s months: %s %s over the whole duration (the monthly figure is the steady monthly cost)" % (n(s.duration_months, 2), n(cost * s.duration_months, 2), price.currency))
    c.notes = ["all data is treated as active storage (modified within 90 days); a table or partition not modified for 90 consecutive days is billed at the cheaper long-term rate, so this is an upper bound",
               "the catalog defines one GiB-month as %s hours of holding, so a GiB held for an average %d-hour month is %s GiB-months" % (n(hours_per_gib_month, 0), HOURS_PER_MONTH, n(month_factor, 4))]
    if s.billing_model == "PHYSICAL":
        c.notes.append("physical billing also charges time-travel and fail-safe bytes: enter the physical size including them if they should be counted")
    else:
        c.notes.append("logical billing: enter the uncompressed size of the data")
    return c


def estimate_on_demand(book: PriceBook, q: QueryInput) -> Component:
    price = book.get("analysis")
    _expect_unit(price, "TiBy")
    # Docs: the minimum is 10 MiB per query AND 10 MiB per referenced table, so a query that references N tables is billed at least N x 10 MiB.
    floor = MIN_BYTES_BILLED_PER_QUERY * q.tables_per_query
    billed_per_query = max(math.ceil(q.avg_bytes_per_query / MIB) * MIB, floor)
    monthly_bytes = q.queries_per_month * billed_per_query
    tib = price.to_unit(monthly_bytes)
    free = max(0.0, min(tib, price.free_quantity - q.free_tib_already_used))
    cost = price.tier_cost(tib, q.free_tib_already_used)
    c = Component("on_demand", "On-Demand Query Processing", True, cost, rate_keys=["analysis"])
    c.consumption = [("Queries per month", "%s (%s)" % (n(q.queries_per_month, 0), q.basis_text)), ("Average data per query", "%s (= %s MiB)" % (q.avg_text, n(q.avg_bytes_per_query / MIB, 3))),
                     ("Billed per query", "%s MiB" % n(billed_per_query / MIB, 3)), ("Billed volume per month", "%s TiB" % n(tib, 6))]
    c.calculation = ["%s queries x %s MiB billed per query (at least %s MiB: 10 MiB x %d table(s)) = %s TiB a month" % (n(q.queries_per_month, 0), n(billed_per_query / MIB, 3), n(floor / MIB, 0), q.tables_per_query, n(tib, 6)),
                     "free tier %s TiB per month, %s already used elsewhere on the billing account, %s applied" % (n(price.free_quantity, 2), n(q.free_tib_already_used, 2), n(free, 6)),
                     "(%s - %s) TiB x %s %s per TiB = %s %s" % (n(tib, 6), n(free, 6), price.list_unit_price, price.currency, n(cost, 4), price.currency)]
    c.consumption.insert(2, ("Tables referenced per query", str(q.tables_per_query)))
    c.notes = ["every query is assumed to process the average amount; skewed workloads cost more because of the minimums and rounding",
               "queries that run on an Enterprise reservation are not billed by bytes: leave them out of this line",
               "the billing docs state the 10 MiB minimum per query and per referenced table but do not say how larger sizes are rounded; rounding up to a whole MiB is an assumption with a negligible effect"]
    if q.days_defaulted:
        c.notes.append("operating days were not given: 30 days a month was assumed")
    if q.avg_bytes_per_query < floor:
        c.notes.append("the 10 MiB minimum applies per query and per referenced table: the average is below %s MiB (%d table(s)), so each query is billed %s MiB" % (n(floor / MIB, 0), q.tables_per_query, n(floor / MIB, 0)))
    return c


def estimate_enterprise(book: PriceBook, e: EnterpriseInput) -> Component:
    price = book.get("edition_ENTERPRISE")
    _expect_unit(price, "h")
    # Documented (reservations-tasks, troubleshooting): "Baseline slots can only be configured in multiples of 50" and autoscale
    # slots "always autoscale to a multiple of 50", both except when covered by excess commitments (not modelled here).
    billed_slots = math.ceil(e.slots / AUTOSCALE_STEP_SLOTS) * AUTOSCALE_STEP_SLOTS
    util = e.autoscale_utilization if e.mode == "autoscale" else 1.0
    hours = e.hours_per_day * e.days_per_month
    slot_hours = billed_slots * util * hours
    cost = price.tier_cost(slot_hours)
    c = Component("enterprise", "Enterprise Edition", True, cost, rate_keys=["edition_ENTERPRISE"])
    c.consumption = [("Mode", e.mode), ("Slots requested", n(e.slots, 0)), ("Slots billed", n(billed_slots, 0)),
                     ("Operating time", "%s hours a day x %s days = %s hours a month" % (n(e.hours_per_day, 2), n(e.days_per_month, 2), n(hours, 2))),
                     ("Slot-hours per month", n(slot_hours, 2))]
    c.calculation = ["%s slots billed x %s of the operating time x %s hours = %s slot-hours" % (n(billed_slots, 0), n(util, 2), n(hours, 2), n(slot_hours, 2)),
                     "%s slot-hours x %s %s per slot-hour = %s %s" % (n(slot_hours, 2), price.list_unit_price, price.currency, n(cost, 2), price.currency)]
    c.notes = ["pay-as-you-go Enterprise Edition rate; capacity commitments (1 or 3 years) are not modelled",
               "the reservation is assumed to exist only during the operating hours stated; baseline slots bill for every minute a reservation exists"]
    if e.mode == "autoscale":
        c.notes.append("autoscale bills the slots it scales to (multiples of 50, rounded up), not the slots used, billed per second with a one-minute minimum by default; with utilization 1.0 this is the ceiling")
    else:
        c.notes.append("baseline slots are always charged, whether used or not, for the whole operating time; the docs do not state the billing unit (second or minute) for baseline")
    if e.slots % AUTOSCALE_STEP_SLOTS:
        what = "autoscale adds slots" if e.mode == "autoscale" else "baseline slots can only be configured"
        c.warnings.append("Enterprise Edition: %s slots requested were rounded up to %s because %s in multiples of 50" % (n(e.slots, 0), n(billed_slots, 0), what))
    return c


def estimate_bi_engine(book: PriceBook, b: BiEngineInput) -> Component:
    price = book.get("bi_engine")
    _expect_unit(price, "GiBy.h")
    gib = b.capacity_bytes / GIB
    hours = b.hours_per_day * b.days_per_month
    gib_hours = gib * hours
    cost = price.tier_cost(gib_hours)
    c = Component("bi_engine", "BI Engine", True, cost, rate_keys=["bi_engine"])
    c.consumption = [("Capacity", "%s (= %s GiB)" % (b.capacity_text, n(gib, 4))), ("Operating time", "%s hours a day x %s days = %s hours a month" % (n(b.hours_per_day, 2), n(b.days_per_month, 2), n(hours, 2))),
                     ("GiB-hours per month", n(gib_hours, 2))]
    c.calculation = ["%s GiB x %s hours = %s GiB-hours" % (n(gib, 4), n(hours, 2), n(gib_hours, 2)),
                     "%s GiB-hours x %s %s per GiB-hour = %s %s" % (n(gib_hours, 2), price.list_unit_price, price.currency, n(cost, 2), price.currency)]
    c.notes = ["reserved capacity bills per GiB-hour whether or not queries use it",
               "no reduction of on-demand bytes is assumed (this is an upper bound): the BigQuery documentation pages that could be read do not say whether BI Engine-accelerated queries are billed for bytes, and the pricing page, which may, could not be retrieved; check total_bytes_billed on a real job",
               "accelerated BI Engine input stages are not counted toward slot reservations (BI Engine monitoring docs), but an Enterprise reservation bills its capacity, so the Enterprise line does not change"]
    lo, hi = BI_ENGINE_DOCUMENTED_GIB
    if not lo <= gib <= hi:
        c.warnings.append("BI Engine: capacity %s GiB is outside the documented %d to %d GiB range; confirm it can be reserved" % (n(gib, 2), lo, hi))
    return c


def estimate_streaming(book: PriceBook, s: IngestInput) -> Component:
    price = book.get("streaming_insert")
    _expect_unit(price, "MiBy")
    mib = price.to_unit(s.size_bytes)
    cost = price.tier_cost(mib)
    c = Component("streaming", "Streaming Inserts (legacy insertAll)", True, cost, rate_keys=["streaming_insert"])
    c.consumption = [("Data streamed per month", "%s (= %s MiB)" % (s.size_text, n(mib, 4)))]
    c.calculation = ["%s MiB x %s %s per MiB = %s %s" % (n(mib, 4), price.list_unit_price, price.currency, n(cost, 4), price.currency)]
    c.notes = ["no free tier: the catalog lists a single rate for this SKU",
               "bills the size of the rows successfully inserted, per the BigQuery pricing docs each row counts at least 1 KB: enter the size as billed (the billing export's usage amount), not the raw payload, when rows are tiny",
               "applies to tabledata.insertAll (for example the streaming writes of insert_rows_json); the Storage Write API is a separate line"]
    return c


def estimate_storage_api(book: PriceBook, s: IngestInput) -> Component:
    price = book.get("storage_api_write")
    _expect_unit(price, "GiBy")
    gib = price.to_unit(s.size_bytes)
    free = max(0.0, min(gib, price.free_quantity - s.free_gib_already_used))
    cost = price.tier_cost(gib, s.free_gib_already_used)
    c = Component("storage_api", "Storage Write API", True, cost, rate_keys=["storage_api_write"])
    c.consumption = [("Data written per month", "%s (= %s GiB)" % (s.size_text, n(gib, 6)))]
    c.calculation = ["free tier %s GiB per month, %s already used elsewhere on the billing account, %s applied" % (n(price.free_quantity, 0), n(s.free_gib_already_used, 2), n(free, 6)),
                     "(%s - %s) GiB x %s %s per GiB = %s %s" % (n(gib, 6), n(free, 6), price.list_unit_price, price.currency, n(cost, 4), price.currency)]
    c.notes = ["the first 2 TiB written each month are free (account-wide, monthly)",
               "Storage Write API reads (BigQuery Storage API - Read) are not modelled: they bill after 300 TiB a month"]
    return c


# ---------------------------------------------------------------- assembly

def estimate_future(book: PriceBook, usage: UsageInputs) -> FutureEstimate:
    comps = [
        estimate_storage(book, usage.storage) if usage.storage else Component("storage", "BigQuery Storage", False),
        estimate_on_demand(book, usage.queries) if usage.queries else Component("on_demand", "On-Demand Query Processing", False),
        estimate_enterprise(book, usage.enterprise) if usage.enterprise else Component("enterprise", "Enterprise Edition", False),
        estimate_bi_engine(book, usage.bi_engine) if usage.bi_engine else Component("bi_engine", "BI Engine", False),
        estimate_streaming(book, usage.streaming) if usage.streaming else Component("streaming", "Streaming Inserts (legacy insertAll)", False),
        estimate_storage_api(book, usage.storage_api) if usage.storage_api else Component("storage_api", "Storage Write API", False),
    ]
    monthly = sum(c.monthly_cost for c in comps if c.monthly_cost is not None)
    currency = next((book.get(k).currency for c in comps for k in c.rate_keys), "")
    assumptions = [
        "All usage figures are the user's expectations, not measurements.",
        "Prices are public list prices from the Cloud Billing Catalog API for region %s, retrieved %s. Negotiated prices, taxes and support are not included." % (usage.region, book.fetched_at),
        "Usage is assumed to repeat every month, so the annual cost is 12 x the monthly cost. Free tiers reset every month: the annual figure does not apply them once a year.",
        "Free tiers are applied once per SKU to the whole monthly quantity. The catalog marks them account-wide (ACCOUNT / MONTHLY) while the billing docs describe the free query tier as per project; with one project and nothing else on the account both agree. If other usage already used part of a tier, state it with the free_*_already_used inputs (default 0).",
        "The on-demand and Enterprise lines are independent: the estimator does not decide which queries run where.",
        "Only BigQuery storage, on-demand queries, Enterprise Edition, BI Engine, legacy streaming inserts and Storage Write API ingestion are covered. Storage API reads, Data Transfer Service, network egress, other editions and other Google Cloud services are not.",
    ]
    warnings = [w for c in comps for w in c.warnings]
    return FutureEstimate(usage.region, currency, book.source, book.fetched_at, comps, monthly, monthly * MONTHS_PER_YEAR, usage, assumptions, warnings)
