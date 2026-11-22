"""
The frozen POC 1 baseline (task 0.3, docs/poc2/baseline.md), pinned so the seed can prove it rebuilt the same data.

The generator is deterministic (fixed SEED and AS_OF), so the seed rebuilds the batch in memory instead of reading the
Phase 1 bucket. The MD5s are copied from the batch folder's manifest.json; if the generator or the data-lake-schema
version ever changes, the seed stops instead of loading different data.
"""

BATCH = "clean_data_20261116_190645"
BATCH_URI = f"gs://data-lake-raw-512405/{BATCH}/"

# Accepted rows per table (0 rejected in POC 1), in the generator's table order.
ROWS = {
    "brands": 4,
    "teams": 5,
    "statuses": 7,
    "alert_types": 11,
    "users": 18,
    "stores": 40,
    "device_locations": 132,
    "alert_incidents": 450,
    "alert_history": 1490,
}

# Base64 MD5 of each CSV, from gs://data-lake-raw-512405/clean_data_20261116_190645/manifest.json.
MD5 = {
    "brands": "LB0N9xNql0j2+W6M1CBFnA==",
    "teams": "3yczFBgnG2N6sGNuTbBfXw==",
    "statuses": "T7c4/NGza9TAwwdeFsi3dA==",
    "alert_types": "BWplVIew+oHR4eYyQ+II0A==",
    "users": "XlSUaeuYeEryQDFUMfGNBA==",
    "stores": "L2XV/B3nRc0Do0hJkcyfKg==",
    "device_locations": "TuKzscbInXnQdzbj7E+fRw==",
    "alert_incidents": "yOBeoQiKDyFFVFny1HbFCg==",
    "alert_history": "VVXQVIKv3jEq30seDjWs8Q==",
}

# Internal-only probe (AT-16): a store with no CRM record and one device. Ids fit the G2 CHECK constraints.
PROBE_STORE_ID = "S999"
PROBE_DEVICE_ID = "D999"
HEARTBEAT_SOURCE = "simulator"
