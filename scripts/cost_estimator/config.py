"""Constants for the BigQuery Future Cost Estimator. Nothing here is a price: prices come from the Cloud Billing Catalog API."""
from __future__ import annotations

DEFAULT_REGION = "us-central1"
CURRENCY = "USD"

# Cloud Billing Catalog API services that carry BigQuery prices.
SERVICE_IDS = {
    "core": "24E6-581D-38E5",         # storage and on-demand analysis
    "reservation": "16B8-3DDA-9F10",  # Editions (Enterprise) slot-hours
    "bi_engine": "650B-3C82-34DB",    # BI Engine GiB-hours
    "storage_api": "DCC9-8DB9-673F",  # Storage Write API (ingestion)
}
SERVICE_DISPLAY_NAMES = {"core": "BigQuery", "reservation": "BigQuery Reservation API", "bi_engine": "BigQuery BI Engine", "storage_api": "BigQuery Storage API"}

# Credentials come from the environment, never from source code or arguments.
API_KEY_ENV = "GCP_BILLING_API_KEY"        # optional: a restricted API key for the Cloud Billing API
QUOTA_PROJECT_ENV = "GCP_QUOTA_PROJECT"    # optional: project billed for API calls when Application Default Credentials are used

LABEL = "ESTIMATED FUTURE COST"
MONTHS_PER_YEAR = 12

# Byte units. Decimal units (KB, MB, GB, TB) are powers of 1000; binary units (KiB, MiB, GiB, TiB) are powers of 1024.
# BigQuery bills in binary units (GiB, TiB).
UNIT_BYTES = {
    "b": 1,
    "kb": 10 ** 3, "mb": 10 ** 6, "gb": 10 ** 9, "tb": 10 ** 12, "pb": 10 ** 15,
    "kib": 2 ** 10, "mib": 2 ** 20, "gib": 2 ** 30, "tib": 2 ** 40, "pib": 2 ** 50,
}
UNIT_NAMES = ["B", "KB", "MB", "GB", "TB", "PB", "KiB", "MiB", "GiB", "TiB", "PiB"]   # as shown in messages
MIB = 2 ** 20
GIB = 2 ** 30
TIB = 2 ** 40

MIN_BYTES_BILLED_PER_QUERY = 10 * MIB   # BigQuery on-demand bills at least 10 MiB per query
AUTOSCALE_STEP_SLOTS = 50               # Editions autoscaling adds slots in multiples of 50, rounded up
BI_ENGINE_DOCUMENTED_GIB = (1, 250)     # capacity range in the BI Engine docs; more needs a quota request
HOURS_PER_MONTH = 730                   # an average month; the catalog defines one storage GiB-month as 721 hours of holding
MAX_DAYS_PER_MONTH = 31
MAX_HOURS_PER_DAY = 24
