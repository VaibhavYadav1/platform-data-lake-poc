import copy
import types

import pytest

from config import API_KEY_ENV, SERVICE_IDS
from pricing_api import (AmbiguousSku, CatalogClient, PriceBook, PriceNotFound, PricingError, SkuPrice, select_sku)
from conftest import ALL_KEYS, client_for


# ---------------------------------------------------------------- retrieval and SKU mapping

def test_every_component_is_priced_from_the_catalog(book):
    assert set(book.prices) == set(ALL_KEYS) == {"storage_active_logical", "storage_active_physical", "analysis", "edition_ENTERPRISE", "bi_engine", "streaming_insert", "storage_api_write"}
    assert book.region == "us-central1" and book.fetched_date == book.fetched_at[:10]


def test_prices_are_fetched_from_the_four_given_service_ids(catalog):
    calls = []
    PriceBook.from_catalog(client_for(catalog, calls), "us-central1", ALL_KEYS)
    assert sorted(c.split("/services/")[1].split("/")[0] for c in calls) == sorted(SERVICE_IDS.values())
    assert all("pageSize=5000" in c and "currencyCode=USD" in c for c in calls)


def test_only_the_services_a_component_needs_are_fetched(catalog):
    calls = []
    PriceBook.from_catalog(client_for(catalog, calls), "us-central1", ["storage_active_logical", "analysis"])
    assert len(calls) == 1 and SERVICE_IDS["core"] in calls[0]            # no Reservation or BI Engine call for a storage-and-queries estimate


def test_paging_follows_next_page_token(catalog):
    pages = {"": {"skus": catalog["skus"]["BigQuery"][:3], "nextPageToken": "T2"}, "T2": {"skus": catalog["skus"]["BigQuery"][3:]}}
    seen = []

    def fetch(url):
        seen.append(url)
        return pages["T2" if "pageToken=T2" in url else ""]
    skus = CatalogClient(fetch=fetch, api_key="", environ={}).service_skus(SERVICE_IDS["core"])
    assert len(skus) == len(catalog["skus"]["BigQuery"]) and len(seen) == 2


def test_regional_sku_is_chosen_not_multi_region(book):
    assert book.get("analysis").regions == ("us-central1",)
    assert book.get("edition_ENTERPRISE").regions == ("us-central1",)
    assert book.get("storage_active_logical").regions == ("us-central1",)
    assert book.get("bi_engine").regions == ("us-central1",)


def test_pay_as_you_go_enterprise_is_chosen_not_commitment_or_plus(book):
    d = book.get("edition_ENTERPRISE").description
    assert d.startswith("BigQuery Enterprise Edition for") and "1 Year" not in d and "Plus" not in d


def test_flat_rate_bi_engine_is_not_chosen(book):
    assert "flat rate" not in book.get("bi_engine").description.lower()


def test_physical_storage_has_its_own_sku(book):
    assert book.get("storage_active_physical").sku_id != book.get("storage_active_logical").sku_id
    assert "physical" in book.get("storage_active_physical").description.lower()


def test_region_specific_pricing_multi_region_us(catalog):
    us = PriceBook.from_catalog(client_for(catalog), "us", ["storage_active_logical", "analysis", "edition_ENTERPRISE", "bi_engine"])
    assert "us" in us.get("analysis").regions and "us-central1" not in us.get("analysis").regions
    assert us.get("edition_ENTERPRISE").regions == ("us",)
    assert "us" in us.get("storage_active_logical").regions and us.region == "us"


def test_unavailable_region_is_a_clear_error_listing_where_it_is_priced(catalog):
    with pytest.raises(PriceNotFound) as e:
        PriceBook.from_catalog(client_for(catalog), "asia-south1", ["analysis"])
    msg = str(e.value)
    assert "asia-south1" in msg and "on-demand analysis" in msg and "regions priced for it" in msg and "us-central1" in msg


def test_a_component_with_no_price_does_not_break_the_others(catalog):
    # Enterprise is not offered in this region of the fixture: asking only for storage still works
    PriceBook.from_catalog(client_for(catalog), "us-central1", ["storage_active_logical"])
    with pytest.raises(PriceNotFound):
        PriceBook.from_catalog(client_for(catalog), "europe-north1", ["edition_ENTERPRISE"])


def test_ambiguous_match_is_an_error_not_a_guess(catalog):
    skus = copy.deepcopy(catalog["skus"]["BigQuery"])
    dup = copy.deepcopy([s for s in skus if s["skuId"] == "3362-E469-6BEF"][0])
    dup["skuId"] = "DUPLICATE"
    with pytest.raises(AmbiguousSku):
        select_sku("analysis", skus + [dup], "us-central1")


def test_wrong_service_id_is_detected(catalog):
    def fetch(url):
        return {"skus": catalog["skus"]["BigQuery BI Engine"]}      # BI Engine SKUs served for the core BigQuery service
    with pytest.raises(PricingError, match="check the service ID"):
        PriceBook.from_catalog(CatalogClient(fetch=fetch, api_key="", environ={}), "us-central1", ["analysis"])


def test_empty_service_is_a_clear_error():
    with pytest.raises(PriceNotFound, match="no SKUs"):
        PriceBook.from_catalog(CatalogClient(fetch=lambda u: {"skus": []}, api_key="", environ={}), "us-central1", ["analysis"])


def test_sku_without_pricing_info_is_rejected():
    with pytest.raises(PriceNotFound):
        SkuPrice.from_catalog({"skuId": "X", "description": "x", "pricingInfo": []}, "svc")


# ---------------------------------------------------------------- units, tiers, free tier

def test_unit_conversions_come_from_the_catalog(book):
    od = book.get("analysis")
    assert od.usage_unit == "TiBy" and od.base_unit_factor == 1024 ** 4 and od.to_unit(2 * 1024 ** 4) == 2
    ed = book.get("edition_ENTERPRISE")
    assert ed.usage_unit == "h" and ed.base_unit_factor == 3600 and ed.to_unit(7200) == 2          # slot-seconds -> slot-hours
    assert book.get("bi_engine").to_unit(10 * 1024 ** 3 * 3600) == 10                              # byte-seconds -> GiB-hours
    assert book.get("storage_active_logical").usage_unit == "GiBy.mo"


def test_free_tiers_and_how_they_are_pooled(book):
    od = book.get("analysis")
    assert od.free_quantity == 1.0 and (od.aggregation_level, od.aggregation_interval) == ("ACCOUNT", "MONTHLY")
    assert book.get("storage_active_logical").free_quantity == 10.0
    assert book.get("edition_ENTERPRISE").free_quantity == 0.0 and book.get("edition_ENTERPRISE").aggregation_level is None
    assert book.get("bi_engine").free_quantity == 0.0


def test_tier_cost_applies_free_tier_then_rate(book):
    od = book.get("analysis")
    assert od.tier_cost(0.5) == 0.0 and od.tier_cost(1.0) == 0.0
    assert od.tier_cost(3.0) == pytest.approx(2.0 * od.list_unit_price)


def test_tier_cost_honours_usage_already_consumed(book):
    od = book.get("analysis")
    assert od.tier_cost(0.5, already_used=0.8) == pytest.approx(0.3 * od.list_unit_price)
    assert od.tier_cost(1.0, already_used=5.0) == pytest.approx(1.0 * od.list_unit_price)


def test_recorded_prices_match_the_catalog_response(book):
    # provenance of the fixture only (recorded 2026-11-25); the estimator hardcodes none of these
    assert (book.get("analysis").list_unit_price, book.get("edition_ENTERPRISE").list_unit_price, book.get("bi_engine").list_unit_price,
            book.get("storage_active_logical").list_unit_price) == (6.25, 0.06, 0.0416, 0.023)


# ---------------------------------------------------------------- API failures and credentials

def test_api_failure_becomes_a_pricing_error():
    def fetch(url):
        raise RuntimeError("connection reset")
    with pytest.raises(PricingError, match="connection reset"):
        CatalogClient(fetch=fetch, api_key="", environ={}).service_skus("X")


def test_api_key_is_redacted_from_errors():
    def fetch(url):
        raise RuntimeError("bad request with SECRETKEY123 inside")
    with pytest.raises(PricingError) as e:
        CatalogClient(fetch=fetch, api_key="SECRETKEY123", environ={}).service_skus("X")
    assert "SECRETKEY123" not in str(e.value) and "***" in str(e.value)


def test_api_key_comes_from_the_environment_and_goes_in_a_header_not_the_url(monkeypatch):
    import requests
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen.update(url=url, headers=headers)
        return types.SimpleNamespace(status_code=200, json=lambda: {"skus": []}, text="")
    monkeypatch.setattr(requests, "get", fake_get)
    CatalogClient(environ={API_KEY_ENV: "ENVKEY999"}).service_skus(SERVICE_IDS["core"])
    assert seen["headers"] == {"x-goog-api-key": "ENVKEY999"} and "ENVKEY999" not in seen["url"] and "key=" not in seen["url"]


def test_http_error_is_reported_without_leaking_the_key(monkeypatch):
    import requests

    def fake_get(url, headers=None, timeout=None):
        return types.SimpleNamespace(status_code=403, json=lambda: {"error": {"message": "API key ENVKEY999 not authorised for this API"}}, text="")
    monkeypatch.setattr(requests, "get", fake_get)
    with pytest.raises(PricingError) as e:
        CatalogClient(environ={API_KEY_ENV: "ENVKEY999"}).service_skus(SERVICE_IDS["core"])
    msg = str(e.value)
    assert "HTTP 403" in msg and "ENVKEY999" not in msg and "not authorised" in msg


def test_network_error_is_reported_without_leaking_the_key(monkeypatch):
    import requests

    def fake_get(url, headers=None, timeout=None):
        raise requests.ConnectionError("cannot connect with ENVKEY999")
    monkeypatch.setattr(requests, "get", fake_get)
    with pytest.raises(PricingError) as e:
        CatalogClient(environ={API_KEY_ENV: "ENVKEY999"}).service_skus("X")
    assert "could not reach" in str(e.value) and "ENVKEY999" not in str(e.value)


def test_no_credentials_explains_how_to_provide_them(monkeypatch):
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError

    def no_creds(scopes=None):
        raise DefaultCredentialsError("none")
    monkeypatch.setattr(google.auth, "default", no_creds)
    with pytest.raises(PricingError, match=API_KEY_ENV):
        CatalogClient(environ={}).service_skus("X")


def test_quota_project_is_set_on_the_credentials_not_as_a_header(monkeypatch):
    """ADC may carry another project as quota project; the credentials overwrite a per-request header, so it must be set on them."""
    import google.auth
    import google.auth.transport.requests as transport
    calls = {}

    class Creds:
        def with_quota_project(self, p):
            calls["quota"] = p
            return self

    class Session:
        def __init__(self, creds):
            calls["creds"] = creds

        def get(self, url, **kw):
            calls["kw"] = kw
            return types.SimpleNamespace(status_code=200, json=lambda: {"skus": []}, text="")
    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (Creds(), "p"))
    monkeypatch.setattr(transport, "AuthorizedSession", Session)
    CatalogClient(environ={"GCP_QUOTA_PROJECT": "the-right-project"}).service_skus("X")
    assert calls["quota"] == "the-right-project" and "headers" not in calls["kw"]


def test_a_rejected_key_names_the_variable_it_came_from_without_leaking_it(monkeypatch):
    """What the real API returned for an invalid key on 2026-11-25: HTTP 400, 'API key not valid. Please pass a valid API key.'"""
    import requests

    def fake_get(url, headers=None, timeout=None):
        return types.SimpleNamespace(status_code=400, json=lambda: {"error": {"message": "API key not valid. Please pass a valid API key."}}, text="")
    monkeypatch.setattr(requests, "get", fake_get)
    with pytest.raises(PricingError) as e:
        CatalogClient(environ={API_KEY_ENV: "BADKEY-12345"}).service_skus(SERVICE_IDS["core"])
    msg = str(e.value)
    assert "HTTP 400" in msg and "API key not valid" in msg and API_KEY_ENV in msg and "BADKEY-12345" not in msg


def test_no_key_hint_when_adc_is_used(monkeypatch):
    import google.auth
    import google.auth.transport.requests as transport

    class Creds:
        pass

    class Session:
        def __init__(self, creds):
            pass

        def get(self, url, **kw):
            return types.SimpleNamespace(status_code=403, json=lambda: {"error": {"message": "denied"}}, text="")
    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (Creds(), "p"))
    monkeypatch.setattr(transport, "AuthorizedSession", Session)
    with pytest.raises(PricingError) as e:
        CatalogClient(environ={}).service_skus("X")
    assert "HTTP 403" in str(e.value) and "was read from" not in str(e.value)


# ---------------------------------------------------------------- multi-region naming differs per service (found by a live sweep of every region)

@pytest.mark.parametrize("regions, location, expected", [
    (["eu"], "eu", True),                          # Editions: EU multi-region
    (["europe"], "eu", True),                      # BI Engine: "BigQuery BI Engine for EU"
    (["us", "europe"], "eu", True),                # storage and queries: one SKU for the US and EU multi-regions
    (["us", "europe"], "us", True),
    (["us"], "us", True),
    (["us"], "eu", False),
    (["eu"], "us", False),
    (["europe-west1"], "eu", False),               # a regional SKU is not the multi-region
    (["us-central1"], "us", False),
    (["us-central1"], "us-central1", True),
    (["us-central1", "us-east1"], "us-central1", False),   # a regional location must be the SKU's only region
    (["EU"], "EU", True),                          # case does not matter
])
def test_region_matching_across_the_catalogs_naming_styles(regions, location, expected):
    from pricing_api import region_matches
    assert region_matches({"serviceRegions": regions}, location) is expected
