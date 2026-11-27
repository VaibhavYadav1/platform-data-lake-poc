"""BigQuery Future Cost Estimator (POC F).

Estimates what BigQuery will cost for the usage you EXPECT, using current public list prices from the Cloud Billing Catalog API.
It does not read existing jobs, usage or billing, and it creates, changes and deletes nothing in Google Cloud.

  python scripts/cost_estimator/main.py estimate --storage-size 5 --storage-unit TB \\
      --queries-per-day 200 --operating-days 22 --query-size 50 --query-unit GB
  python scripts/cost_estimator/main.py estimate --config scripts/cost_estimator/example_usage.json --out-dir cost_report
  python scripts/cost_estimator/main.py prices --region us-central1

Credentials (never in source or arguments): set GCP_BILLING_API_KEY to an API key for the Cloud Billing API, or sign in with
'gcloud auth application-default login' (optionally set GCP_QUOTA_PROJECT).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import report_generator as rg  # noqa: E402
from config import CURRENCY, DEFAULT_REGION  # noqa: E402
from cost_calculator import estimate_future, n  # noqa: E402
from pricing_api import RULES, CatalogClient, PriceBook, PricingError  # noqa: E402
from usage_inputs import InputError, parse_inputs  # noqa: E402


def make_client() -> CatalogClient:
    return CatalogClient()          # reads GCP_BILLING_API_KEY / GCP_QUOTA_PROJECT from the environment; tests replace this


def _set(section: dict, key: str, value) -> None:
    if value is not None:
        section[key] = value


def raw_from_flags(a) -> dict:
    """Turns command-line flags into the same dict a JSON file holds. Only the components the user asked for are created."""
    raw: dict = {}
    _set(raw, "region", a.region)
    st: dict = {}
    _set(st, "size", a.storage_size); _set(st, "unit", a.storage_unit); _set(st, "duration_months", a.storage_months)
    _set(st, "billing_model", a.storage_model); _set(st, "free_gib_already_used", a.storage_free_gib_used)
    if st:
        raw["storage"] = st
    q: dict = {}
    _set(q, "per_day", a.queries_per_day); _set(q, "per_month", a.queries_per_month); _set(q, "operating_days", a.operating_days)
    _set(q, "avg_data_per_query", a.query_size); _set(q, "unit", a.query_unit); _set(q, "tables_per_query", a.tables_per_query)
    _set(q, "free_tib_already_used", a.on_demand_free_tib_used)
    if q:
        raw["queries"] = q
    e: dict = {}
    _set(e, "slots", a.enterprise_slots); _set(e, "mode", a.enterprise_mode); _set(e, "hours_per_day", a.enterprise_hours_per_day)
    _set(e, "days_per_month", a.enterprise_days_per_month); _set(e, "autoscale_utilization", a.enterprise_utilization)
    if e or a.enterprise:
        e["enabled"] = True
        raw["enterprise"] = e
    b: dict = {}
    _set(b, "capacity", a.bi_capacity); _set(b, "unit", a.bi_unit); _set(b, "hours_per_day", a.bi_hours_per_day); _set(b, "days_per_month", a.bi_days_per_month)
    if b or a.bi_engine:
        b["enabled"] = True
        raw["bi_engine"] = b
    sm: dict = {}
    _set(sm, "size_per_month", a.streaming_size); _set(sm, "unit", a.streaming_unit)
    if sm:
        raw["streaming"] = sm
    sa: dict = {}
    _set(sa, "size_per_month", a.storage_api_size); _set(sa, "unit", a.storage_api_unit); _set(sa, "free_gib_already_used", a.storage_api_free_gib_used)
    if sa:
        raw["storage_api"] = sa
    return raw


def merge(base: dict, over: dict) -> dict:
    """Flags win over the file, field by field. A monthly query count replaces a daily one (and the reverse)."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            section = out[k]
            if k == "queries":
                if "per_month" in v:
                    section.pop("per_day", None); section.pop("operating_days", None)
                if "per_day" in v:
                    section.pop("per_month", None)
            section.update(v)
        else:
            out[k] = v
    return out


def load_raw(a) -> dict:
    raw: dict = {}
    if a.config:
        try:
            with open(a.config, encoding="utf-8") as f:
                raw = json.load(f)
        except OSError as e:
            raise InputError("cannot read %s: %s" % (a.config, e.strerror))
        except ValueError as e:
            raise InputError("%s is not valid JSON: %s" % (a.config, e))
        if not isinstance(raw, dict):
            raise InputError("%s must hold a JSON object" % a.config)
    return merge(raw, raw_from_flags(a))


def cmd_estimate(a) -> int:
    usage = parse_inputs(load_raw(a))
    book = PriceBook.from_catalog(make_client(), usage.region, usage.price_keys())
    report = rg.build_report(estimate_future(book, usage), book)
    if a.out_dir:
        for p in rg.write_outputs(report, a.out_dir):
            print("wrote", p, file=sys.stderr)
    print(json.dumps(report, indent=2) if a.format == "json" else rg.render_markdown(report))
    return 0


def cmd_prices(a) -> int:
    book = PriceBook.from_catalog(make_client(), (a.region or DEFAULT_REGION).lower(), list(RULES))
    print("Region %s. Retrieved %s from %s. Public list prices in %s." % (book.region, book.fetched_at, book.source, CURRENCY))
    for key, p in book.prices.items():
        print("%-26s %-15s %-66s per %-8s tiers %s  aggregation %s/%s  effective %s" % (
            key, p.sku_id, p.description[:66], p.usage_unit, [(t[0], t[1]) for t in p.tiers], p.aggregation_level, p.aggregation_interval, p.effective_time))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("estimate", help="estimate the future monthly and annual BigQuery cost of the usage you expect")
    p.add_argument("--config", help="JSON file with the expected usage (see example_usage.json); flags override it")
    p.add_argument("--region", help="pricing region (default %s)" % DEFAULT_REGION)
    p.add_argument("--out-dir", help="also write estimate.md and estimate.json here")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    g = p.add_argument_group("storage")
    g.add_argument("--storage-size", type=float); g.add_argument("--storage-unit", help="required with --storage-size: KB MB GB TB PB (decimal) or KiB MiB GiB TiB PiB (binary)")
    g.add_argument("--storage-months", type=float, help="months the data is stored (default 1)")
    g.add_argument("--storage-model", choices=["logical", "physical"], help="billing model the size is expressed in (default logical)")
    g.add_argument("--storage-free-gib-used", type=float, help="free storage already used this month by other usage on the billing account")
    g = p.add_argument_group("on-demand queries")
    g.add_argument("--queries-per-day", type=float); g.add_argument("--queries-per-month", type=float)
    g.add_argument("--operating-days", type=float, help="days a month the queries run (with --queries-per-day; default 30)")
    g.add_argument("--query-size", type=float, help="average data processed per query"); g.add_argument("--query-unit", help="unit of --query-size (required)")
    g.add_argument("--tables-per-query", type=float, help="tables each query references: the 10 MiB minimum applies per table (default 1)")
    g.add_argument("--on-demand-free-tib-used", type=float, help="free query TiB already used this month by other usage on the billing account")
    g = p.add_argument_group("Enterprise Edition (optional)")
    g.add_argument("--enterprise", action="store_true", help="include Enterprise Edition")
    g.add_argument("--enterprise-slots", type=float); g.add_argument("--enterprise-mode", choices=["baseline", "autoscale"])
    g.add_argument("--enterprise-hours-per-day", type=float); g.add_argument("--enterprise-days-per-month", type=float)
    g.add_argument("--enterprise-utilization", type=float, help="autoscale only: share of operating time the slots are scaled up (0 to 1, default 1)")
    g = p.add_argument_group("BI Engine (optional)")
    g.add_argument("--bi-engine", action="store_true", help="include BI Engine")
    g.add_argument("--bi-capacity", type=float); g.add_argument("--bi-unit", help="unit of --bi-capacity (required)")
    g.add_argument("--bi-hours-per-day", type=float); g.add_argument("--bi-days-per-month", type=float)
    g = p.add_argument_group("streaming inserts, legacy insertAll (optional)")
    g.add_argument("--streaming-size", type=float, help="data streamed per month"); g.add_argument("--streaming-unit", help="unit of --streaming-size (required)")
    g = p.add_argument_group("Storage Write API (optional)")
    g.add_argument("--storage-api-size", type=float, help="data written per month"); g.add_argument("--storage-api-unit", help="unit of --storage-api-size (required)")
    g.add_argument("--storage-api-free-gib-used", type=float, help="free Storage Write API GiB already used this month by other usage on the billing account")
    p.set_defaults(fn=cmd_estimate)

    p = sub.add_parser("prices", help="print the BigQuery prices the Catalog API returns for a region")
    p.add_argument("--region", help="default %s" % DEFAULT_REGION)
    p.set_defaults(fn=cmd_prices)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (InputError, PricingError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
