import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pricing_api import RULES, CatalogClient, PriceBook  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "catalog_excerpt.json")
ALL_KEYS = list(RULES)


@pytest.fixture(scope="session")
def catalog():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def make_fetch(catalog, calls=None):
    """A fake Catalog API: serves the recorded SKUs by service ID and records every URL asked for."""
    by_id = {s["name"].split("/")[1]: s["displayName"] for s in catalog["services"]}

    def fetch(url):
        if calls is not None:
            calls.append(url)
        for sid, display in by_id.items():
            if "/services/%s/skus" % sid in url:
                return {"skus": catalog["skus"][display]}
        raise AssertionError("unexpected URL " + url)
    return fetch


def client_for(catalog, calls=None):
    return CatalogClient(fetch=make_fetch(catalog, calls), api_key="", environ={})


@pytest.fixture(scope="session")
def book(catalog):
    return PriceBook.from_catalog(client_for(catalog), "us-central1", ALL_KEYS)
