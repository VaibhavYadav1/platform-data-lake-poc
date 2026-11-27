"""Cloud Billing Catalog API client and the BigQuery price book.

Every price in this tool comes from GET https://cloudbilling.googleapis.com/v1/services/{id}/skus (public list prices). The API does
not return negotiated or contract prices, and it can serve prices up to 12 hours old (stated in the API reference).

BigQuery prices sit in three Catalog services (config.SERVICE_IDS). SKUs are chosen by rule (service, region, resource group,
description), never by hardcoded ID. A rule that matches nothing or several SKUs raises PricingError instead of guessing.

Credentials: an API key in the GCP_BILLING_API_KEY environment variable (sent in the x-goog-api-key header, so it never appears in a URL),
or else Application Default Credentials. A key is never logged: error messages are redacted.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from config import API_KEY_ENV, CURRENCY, QUOTA_PROJECT_ENV, SERVICE_DISPLAY_NAMES, SERVICE_IDS

CATALOG_BASE = "https://cloudbilling.googleapis.com/v1"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
SOURCE = "Cloud Billing Catalog API v1 (public list prices)"


class PricingError(Exception):
    """A price could not be retrieved: API failure, no credentials, or no matching SKU."""


class PriceNotFound(PricingError):
    pass


class AmbiguousSku(PricingError):
    pass


def money(m: dict) -> float:
    return float(int(m.get("units") or 0)) + int(m.get("nanos") or 0) / 1e9


@dataclass(frozen=True)
class SkuPrice:
    sku_id: str
    description: str
    service: str
    regions: tuple
    resource_group: str
    usage_unit: str                 # e.g. TiBy, GiBy.mo, GiBy.h, h
    base_unit: str                  # e.g. By, By.s, s
    base_unit_factor: float         # base units per usage unit (from the API)
    tiers: tuple                    # ((start_usage_amount, unit_price), ...) ascending
    currency: str
    aggregation_level: str | None   # ACCOUNT / PROJECT / None (no pooled tier)
    aggregation_interval: str | None  # MONTHLY / DAILY / None
    effective_time: str | None

    def to_unit(self, base_amount: float) -> float:
        """Convert an amount in base units (bytes, byte-seconds, seconds) to this SKU's usage unit."""
        return base_amount / self.base_unit_factor

    def cumulative_cost(self, quantity: float) -> float:
        total = 0.0
        for i, (start, price) in enumerate(self.tiers):
            end = self.tiers[i + 1][0] if i + 1 < len(self.tiers) else float("inf")
            if quantity > start:
                total += (min(quantity, end) - start) * price
        return total

    def tier_cost(self, quantity: float, already_used: float = 0.0) -> float:
        """Cost of `quantity` more units in one aggregation period, after `already_used` units were consumed in it."""
        return self.cumulative_cost(already_used + quantity) - self.cumulative_cost(already_used)

    @property
    def free_quantity(self) -> float:
        """Units free in each aggregation period (the first tier, when it costs nothing and a later tier does)."""
        if len(self.tiers) > 1 and self.tiers[0][1] == 0.0:
            return self.tiers[1][0] - self.tiers[0][0]
        return 0.0

    @property
    def list_unit_price(self) -> float:
        """The price per usage unit once any free tier is used up."""
        return self.tiers[-1][1]

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["regions"] = list(self.regions)
        d["tiers"] = [list(t) for t in self.tiers]
        return d

    @classmethod
    def from_catalog(cls, sku: dict, service: str) -> "SkuPrice":
        infos = sku.get("pricingInfo") or []
        if not infos:
            raise PriceNotFound("SKU %s has no pricing information" % sku.get("skuId"))
        info = infos[-1]  # the timeline is chronological; the last entry is the latest
        pe = info["pricingExpression"]
        tiers = tuple((float(t.get("startUsageAmount") or 0), money(t["unitPrice"])) for t in pe["tieredRates"])
        agg = info.get("aggregationInfo") or {}
        return cls(
            sku_id=sku["skuId"], description=sku["description"], service=service, regions=tuple(sku.get("serviceRegions", [])),
            resource_group=sku.get("category", {}).get("resourceGroup", ""), usage_unit=pe["usageUnit"], base_unit=pe.get("baseUnit", ""),
            base_unit_factor=float(pe.get("baseUnitConversionFactor") or 1), tiers=tiers,
            currency=pe["tieredRates"][0]["unitPrice"].get("currencyCode", ""),
            aggregation_level=agg.get("aggregationLevel") or None, aggregation_interval=agg.get("aggregationInterval") or None,
            effective_time=info.get("effectiveTime"))


class CatalogClient:
    """Read-only client. `fetch(url) -> dict` is injectable for tests."""

    def __init__(self, fetch: Callable[[str], dict] | None = None, api_key: str | None = None, quota_project: str | None = None,
                 currency: str = CURRENCY, environ: dict | None = None):
        env = os.environ if environ is None else environ
        self._fetch = fetch
        self._key = api_key if api_key is not None else env.get(API_KEY_ENV)
        self._quota_project = quota_project if quota_project is not None else env.get(QUOTA_PROJECT_ENV)
        self._currency = currency
        self._session = None

    def _redact(self, text: str) -> str:
        return text.replace(self._key, "***") if self._key else text

    def _adc_session(self):
        try:
            import google.auth
            from google.auth.exceptions import DefaultCredentialsError
            from google.auth.transport.requests import AuthorizedSession
        except ImportError as e:  # pragma: no cover
            raise PricingError("google-auth is not installed: %s" % e)
        if self._session is None:
            try:
                creds, _ = google.auth.default(scopes=SCOPES)
            except DefaultCredentialsError:
                raise PricingError("no credentials: set %s to an API key for the Cloud Billing API, or run 'gcloud auth application-default login'" % API_KEY_ENV)
            # ADC can carry its own quota project, and the credentials overwrite a per-request header, so set it on the credentials.
            if self._quota_project and hasattr(creds, "with_quota_project"):
                creds = creds.with_quota_project(self._quota_project)
            self._session = AuthorizedSession(creds)
        return self._session

    def _default_fetch(self, url: str) -> dict:
        import requests
        where = url.split("?")[0].replace(CATALOG_BASE, "")
        try:
            if self._key:
                r = requests.get(url, headers={"x-goog-api-key": self._key}, timeout=60)
            else:
                r = self._adc_session().get(url, timeout=60)
        except PricingError:
            raise
        except Exception as e:  # network errors, expired credentials
            raise PricingError("could not reach the Cloud Billing Catalog API (%s): %s" % (type(e).__name__, self._redact(str(e))[:200]))
        if r.status_code != 200:
            try:
                msg = r.json().get("error", {}).get("message", "")
            except ValueError:
                msg = ""
            hint = (" (the key was read from %s: check that it is valid and that its API restriction allows the Cloud Billing API)" % API_KEY_ENV) if (self._key and r.status_code in (400, 401, 403)) else ""
            raise PricingError("Cloud Billing Catalog API returned HTTP %d for %s: %s%s" % (r.status_code, where, self._redact(msg)[:300] or "no message", hint))
        try:
            return r.json()
        except ValueError:
            raise PricingError("Cloud Billing Catalog API returned an unreadable response for %s" % where)

    def get(self, url: str) -> dict:
        try:
            return (self._fetch or self._default_fetch)(url)
        except PricingError:
            raise
        except Exception as e:
            raise PricingError("price retrieval failed (%s): %s" % (type(e).__name__, self._redact(str(e))[:200]))

    def service_skus(self, service_id: str) -> list:
        out, token = [], ""
        while True:
            url = "%s/services/%s/skus?pageSize=5000&currencyCode=%s%s" % (CATALOG_BASE, service_id, self._currency, ("&pageToken=" + token) if token else "")
            page = self.get(url)
            out += page.get("skus", [])
            token = page.get("nextPageToken", "")
            if not token:
                return out


def _group(s: dict) -> str:
    return s.get("category", {}).get("resourceGroup", "")


def _desc(s: dict) -> str:
    return s.get("description", "").lower()


_ENTERPRISE_RE = re.compile(r"^bigquery enterprise edition for ")   # pay-as-you-go: excludes "Enterprise Plus" and the 1 Year / 3 Years commitments

# key -> (service key, description of the component, predicate on a raw SKU). The region test is applied separately.
RULES: dict = {
    "storage_active_logical": ("core", "active logical storage", lambda s: _group(s) == "ActiveStorage"),
    "storage_active_physical": ("core", "active physical storage", lambda s: _group(s) == "PhysicalStorage" and _desc(s).startswith("active physical")),
    "analysis": ("core", "on-demand analysis", lambda s: _group(s) == "OnDemandAnalysis" and (_desc(s) == "analysis" or _desc(s).startswith("analysis ("))),
    "edition_ENTERPRISE": ("reservation", "Enterprise Edition slot-hours", lambda s: bool(_ENTERPRISE_RE.match(_desc(s)))),
    "bi_engine": ("bi_engine", "BI Engine capacity", lambda s: _desc(s).startswith("bigquery bi engine for ") and "flat rate" not in _desc(s)),
    "streaming_insert": ("core", "legacy streaming insert (tabledata.insertAll)", lambda s: _group(s) == "Streaming" and _desc(s).startswith("streaming insert")),
    "storage_api_write": ("storage_api", "Storage Write API ingestion", lambda s: _group(s) == "Streaming" and _desc(s).startswith("bigquery storage api - write")),
}

# How the catalog names the multi-regions in serviceRegions. It is not consistent across services: the EU multi-region is ['eu'] for
# Editions, ['europe'] for BI Engine, and storage and queries share one SKU listed as ['us', 'europe'].
_MULTI_REGION_ALIAS = {"us": ("us",), "eu": ("eu", "europe")}


def region_matches(sku: dict, region: str) -> bool:
    """A regional location must be the SKU's only region. A multi-region (US, EU) matches a SKU whose serviceRegions lists it
    (the US and EU multi-regions share one SKU for some services, so serviceRegions can be ['us', 'europe'])."""
    loc = region.lower()
    regions = [r.lower() for r in sku.get("serviceRegions", [])]
    if loc in _MULTI_REGION_ALIAS:
        return any(a in regions for a in _MULTI_REGION_ALIAS[loc])   # geoTaxonomy is not reliable here: the BI Engine US SKU is tagged REGIONAL
    return regions == [loc]


def select_sku(key: str, skus: list, region: str) -> dict:
    _, label, pred = RULES[key]
    matching = [s for s in skus if pred(s)]
    hits = [s for s in matching if region_matches(s, region)]
    if not hits:
        offered = sorted({r for s in matching for r in s.get("serviceRegions", [])})
        raise PriceNotFound("no %s price for region %r in the Catalog API%s" % (
            label, region, ("; regions priced for it: " + ", ".join(offered)) if offered else "; the API returned no SKU of this kind"))
    if len(hits) > 1:
        raise AmbiguousSku("%s matched %d SKUs in %s: %s" % (label, len(hits), region, [h["skuId"] + " " + h["description"] for h in hits]))
    return hits[0]


class PriceBook:
    def __init__(self, prices: dict, region: str, fetched_at: str, source: str = SOURCE):
        self.prices = prices
        self.region = region
        self.fetched_at = fetched_at
        self.source = source

    @property
    def fetched_date(self) -> str:
        return self.fetched_at[:10]

    def get(self, key: str) -> SkuPrice:
        if key not in self.prices:
            raise PriceNotFound("price %s was not retrieved" % key)
        return self.prices[key]

    @classmethod
    def from_catalog(cls, client: CatalogClient, region: str, keys: list) -> "PriceBook":
        """Retrieves only the services the requested keys need, so a missing Enterprise or BI Engine price cannot break a storage estimate."""
        skus_by_service: dict = {}
        prices = {}
        for key in keys:
            svc = RULES[key][0]
            if svc not in skus_by_service:
                skus = client.service_skus(SERVICE_IDS[svc])
                if not skus:
                    raise PriceNotFound("the Catalog API returned no SKUs for %s (service %s)" % (SERVICE_DISPLAY_NAMES[svc], SERVICE_IDS[svc]))
                seen = skus[0].get("category", {}).get("serviceDisplayName")
                if seen != SERVICE_DISPLAY_NAMES[svc]:
                    raise PricingError("service %s returned SKUs of %r, expected %r: check the service ID" % (SERVICE_IDS[svc], seen, SERVICE_DISPLAY_NAMES[svc]))
                skus_by_service[svc] = skus
            prices[key] = SkuPrice.from_catalog(select_sku(key, skus_by_service[svc], region), SERVICE_DISPLAY_NAMES[svc])
        return cls(prices, region, datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return {"source": self.source, "region": self.region, "fetched_at": self.fetched_at, "prices": {k: v.to_dict() for k, v in self.prices.items()}}
