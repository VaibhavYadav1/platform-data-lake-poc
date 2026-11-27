"""The Estimated Future Cost report: Markdown for people, JSON for programs.

The report never shows an actual or historical cost. It keeps three things apart: what the user provided (inputs and assumptions),
what the Catalog API returned (prices), and what was calculated from the two.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass

from config import LABEL
from cost_calculator import FutureEstimate, n
from pricing_api import PriceBook
from usage_inputs import UsageInputs


def money(x, cur: str = "USD") -> str:
    return "N/A (not requested)" if x is None else "%s %s" % (n(x, 2), cur)


def describe_inputs(u: UsageInputs) -> dict:
    """The user's own inputs, as text, grouped by component."""
    out = {"Region": [("Pricing region", u.region)]}
    if u.storage:
        s = u.storage
        out["BigQuery Storage"] = [("Expected data stored", s.size_text), ("Storage duration", "%s month(s)" % n(s.duration_months, 2)), ("Billing model", s.billing_model.lower()),
                                   ("Free storage already used this month elsewhere on the account", "%s GiB-months" % n(s.free_gib_already_used, 2))]
    if u.queries:
        q = u.queries
        out["On-Demand Query Processing"] = [("Query volume", q.basis_text), ("Average data processed per query", q.avg_text), ("Tables referenced per query", str(q.tables_per_query)),
                                             ("Free query volume already used this month elsewhere on the account", "%s TiB" % n(q.free_tib_already_used, 2))]
    if u.enterprise:
        e = u.enterprise
        rows = [("Mode", e.mode), ("Slot capacity", n(e.slots, 0)), ("Operating hours per day", n(e.hours_per_day, 2)), ("Operating days per month", n(e.days_per_month, 2))]
        if e.mode == "autoscale":
            rows.append(("Autoscale utilization (share of operating time scaled up)", n(e.autoscale_utilization, 2)))
        out["Enterprise Edition"] = rows
    if u.bi_engine:
        b = u.bi_engine
        out["BI Engine"] = [("Capacity", b.capacity_text), ("Operating hours per day", n(b.hours_per_day, 2)), ("Operating days per month", n(b.days_per_month, 2))]
    if u.streaming:
        out["Streaming Inserts (legacy insertAll)"] = [("Data streamed per month", u.streaming.size_text)]
    if u.storage_api:
        out["Storage Write API"] = [("Data written per month", u.storage_api.size_text),
                                    ("Free GiB already used this month elsewhere on the account", n(u.storage_api.free_gib_already_used, 2))]
    return out


def _plain(o):
    if is_dataclass(o):
        return {k: _plain(v) for k, v in asdict(o).items()}
    if isinstance(o, dict):
        return {str(k): _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    return o


def build_report(est: FutureEstimate, book: PriceBook) -> dict:
    rates = []
    for c in est.components:
        for key in c.rate_keys:
            p = book.get(key)
            rates.append({"component": c.name, "key": key, "sku_id": p.sku_id, "description": p.description, "unit": p.usage_unit, "tiers": [list(t) for t in p.tiers],
                          "aggregation": "%s/%s" % (p.aggregation_level, p.aggregation_interval), "effective_time": p.effective_time, "currency": p.currency})
    return {
        "label": LABEL, "region": est.region, "currency": est.currency,
        "prices": {"source": est.price_source, "retrieved_at": est.prices_fetched_at, "retrieved_date": est.prices_fetched_at[:10], "kind": "public list prices", "rates": rates},
        "inputs_provided_by_user": {k: [list(r) for r in v] for k, v in describe_inputs(est.usage).items()},
        "components": [{"key": c.key, "name": c.name, "requested": c.requested, "monthly_cost": c.monthly_cost, "annual_cost": c.annual_cost,
                        "consumption": [list(x) for x in c.consumption], "calculation": c.calculation, "notes": c.notes} for c in est.components],
        "total": {"monthly": est.monthly_total, "annual": est.annual_total},
        "assumptions": est.assumptions, "warnings": est.warnings}


def render_markdown(r: dict) -> str:
    cur = r["currency"] or "USD"
    L = ["# Estimated Future Cost: BigQuery", "",
         "**%s.** This is a projection from the usage you expect and current public list prices. It is not an actual cost and not a historical cost." % r["label"], "",
         "- Pricing region: **%s**" % r["region"],
         "- Pricing retrieved: **%s** (%s) from %s" % (r["prices"]["retrieved_date"], r["prices"]["retrieved_at"], r["prices"]["source"]),
         "- These are **public list prices**; negotiated or contract prices are not included.", "",
         "## Cost breakdown", "", "| Component | Estimated Monthly Cost | Estimated Annual Cost |", "|---|---:|---:|"]
    for c in r["components"]:
        L.append("| %s | %s | %s |" % (c["name"], money(c["monthly_cost"], cur), money(c["annual_cost"], cur)))
    L += ["| **Total Estimated Monthly Cost** | **%s** | |" % money(r["total"]["monthly"], cur), "| **Total Estimated Annual Cost** | | **%s** |" % money(r["total"]["annual"], cur), "",
          "Estimated annual cost: **%s** (12 x the estimated monthly cost)." % money(r["total"]["annual"], cur), ""]

    L += ["## Expected resource consumption", "", "Calculated from your inputs.", ""]
    for c in r["components"]:
        if c["requested"]:
            L += ["**%s**" % c["name"], ""] + ["- %s: %s" % (a, b) for a, b in c["consumption"]] + [""]

    L += ["## Pricing rates retrieved from the API", "", "Retrieved %s from the Cloud Billing Catalog API, region `%s`. Prices are in %s." % (r["prices"]["retrieved_date"], r["region"], cur), ""]
    if r["prices"]["rates"]:
        L += ["| Component | SKU | Description | Unit | Tiers (from usage, price) | Aggregation | Effective |", "|---|---|---|---|---|---|---|"]
        for p in r["prices"]["rates"]:
            L.append("| %s | %s | %s | %s | %s | %s | %s |" % (p["component"], p["sku_id"], p["description"], p["unit"], "; ".join("from %g: %g" % (t[0], t[1]) for t in p["tiers"]),
                                                              p["aggregation"], p["effective_time"] or ""))
        L.append("")
    else:
        L += ["No price was needed.", ""]

    L += ["## Inputs you provided (your assumptions)", ""]
    for group, rows in r["inputs_provided_by_user"].items():
        L += ["**%s**" % group, ""] + ["- %s: %s" % (a, b) for a, b in rows] + [""]

    L += ["## Calculation details", ""]
    for c in r["components"]:
        if c["requested"]:
            L += ["**%s**" % c["name"], ""] + ["%d. %s" % (i, s) for i, s in enumerate(c["calculation"], 1)] + [""]
            L += ["Notes:"] + ["- " + x for x in c["notes"]] + [""]
    L += ["## Assumptions", ""] + ["- " + a for a in r["assumptions"]] + [""]
    if r["warnings"]:
        L += ["## Warnings", ""] + ["- " + w for w in r["warnings"]] + [""]
    return "\n".join(L)


def write_outputs(report: dict, out_dir: str) -> list:
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for name, text in (("estimate.md", render_markdown(report)), ("estimate.json", json.dumps(report, indent=2))):
        p = os.path.join(out_dir, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        paths.append(p)
    return paths
