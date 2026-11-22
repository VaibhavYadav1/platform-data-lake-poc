"""No database needed: the vendored generator still rebuilds the frozen baseline, and the pins fit the schema."""

import hashlib
import re
from pathlib import Path

import pytest

from simulator import baseline, seed
from simulator.config import Settings
from simulator.vendor import generate_synthetic_data as gen

VENDOR_SHA256 = "9d9b747d2cd5d76dc9da58301fa363c93e7d83c3ef57ed474ab8c4cade2d3f24"  # commit 4edc2ba


def test_vendored_generator_is_unchanged():
    path = Path(gen.__file__)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == VENDOR_SHA256, "never edit vendor/ (see vendor/README.md)"


def test_rebuilt_batch_matches_the_baseline():
    rows = seed.build_rows(baseline.BATCH)  # raises if any MD5 or count differs
    assert {t: len(r) for t, r in rows.items()} == baseline.ROWS


@pytest.mark.parametrize("name", ["clean_data_20261105_174601", "planted_errors_20261116_190645", "x"])
def test_only_the_frozen_batch_is_seeded(name):
    with pytest.raises(seed.SeedError):
        seed.build_rows(name)


def test_probe_ids_pass_the_schema_checks():
    sql = (Path(__file__).resolve().parents[2] / "sql" / "g2" / "schema.sql").read_text(encoding="utf-8")
    store_check = re.search(r"store_id\s+TEXT\s+PRIMARY KEY CHECK \(store_id ~ '([^']+)'\)", sql).group(1)
    device_check = re.search(r"device_id\s+TEXT\s+PRIMARY KEY CHECK \(device_id ~ '([^']+)'\)", sql).group(1)
    assert re.fullmatch(store_check, baseline.PROBE_STORE_ID)
    assert re.fullmatch(device_check, baseline.PROBE_DEVICE_ID)


def test_reset_is_local_only():
    assert Settings.from_env({"PG_HOST": "localhost"}).is_local
    assert not Settings.from_env({"PG_HOST": "10.1.2.3"}).is_local
    assert not Settings.from_env({"PG_HOST": "localhost", "PG_INSTANCE": "p:r:i"}).is_local
