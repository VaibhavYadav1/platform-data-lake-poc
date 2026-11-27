"""sim_g2_datalake writer (task A9): seeds `wheel` once and appends `wheel_event` rows with a load job (free), not
streaming inserts. `derived_alert` is written by the scheduled query, never here.

The pure functions (build_wheels, generate_events) need no GCP access. Tables must exist first
(python -m simulator.create_sim_g2_datalake). Target project/dataset: LakeSettings (G2DL_PROJECT, G2DL_DATASET).
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

from .config import LakeSettings

WHEELS_PER_STORE = 20
INACTIVE_SHARE = 0.05
UNKNOWN_WHEEL_RATE = 0.005  # DQ43: an event naming a wheel that does not exist
EVENTS_PER_TICK = (50, 200)  # at RATE=1.0
TICK_MINUTES = 5
EVENT_TYPES = ("LOCK", "UNLOCK", "EXIT_ATTEMPT", "LOW_BATTERY")
EVENT_WEIGHTS = (40, 35, 15, 10)
SEED_AS_OF = datetime(2026, 10, 20, tzinfo=timezone.utc)  # same AS_OF as the G2 seed


class WheelWriterError(Exception):
    pass


def wheel_id(n: int) -> str:
    return f"W{n:05d}"


def build_wheels(store_ids, seed: int = 42, per_store: int = WHEELS_PER_STORE) -> list[dict]:
    """Deterministic wheel rows: `per_store` wheels for each store id, in store order."""
    rng = random.Random(seed)
    rows, n = [], 0
    for store_id in sorted(store_ids):
        for _ in range(per_store):
            n += 1
            installed = SEED_AS_OF - timedelta(days=rng.randint(30, 365), minutes=rng.randint(0, 1439))
            rows.append({
                "wheel_id": wheel_id(n),
                "g2_store_id": store_id,
                "cart_id": f"C{n:05d}",
                "installed_at": installed.isoformat(),
                "status": "INACTIVE" if rng.random() < INACTIVE_SHARE else "ACTIVE",
            })
    return rows


def generate_events(wheel_ids, now: datetime, rng: random.Random, rate: float = 1.0) -> list[dict]:
    """One tick of wheel events: 50-200 x rate rows over the last tick, ~0.5% naming an unknown wheel."""
    if not wheel_ids:
        raise WheelWriterError("no wheels to emit events for: seed the wheel table first")
    known = set(wheel_ids)
    low, high = EVENTS_PER_TICK
    count = max(1, round(rng.randint(low, high) * rate))
    loaded_at = now.isoformat()
    rows = []
    for _ in range(count):
        if rng.random() < UNKNOWN_WHEEL_RATE:
            wid = wheel_id(rng.randint(90000, 99999))
            while wid in known:
                wid = wheel_id(rng.randint(90000, 99999))
        else:
            wid = rng.choice(wheel_ids)
        ts = now - timedelta(seconds=rng.randint(0, TICK_MINUTES * 60 - 1))
        rows.append({
            "event_id": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
            "wheel_id": wid,
            "event_type": rng.choices(EVENT_TYPES, EVENT_WEIGHTS)[0],
            "event_ts": ts.isoformat(),
            "_loaded_at": loaded_at,
        })
    return rows


def _client(lake: LakeSettings):
    from google.cloud import bigquery
    return bigquery.Client(project=lake.project, location=lake.location)


def _load(client, lake: LakeSettings, table: str, rows: list[dict], disposition: str) -> int:
    from google.cloud import bigquery
    from .create_sim_g2_datalake import TABLES, schema_fields
    config = bigquery.LoadJobConfig(schema=schema_fields(TABLES[table]), write_disposition=disposition)
    client.load_table_from_json(rows, f"{lake.project}.{lake.dataset}.{table}", job_config=config).result()
    return len(rows)


def active_store_ids(lake: LakeSettings) -> list[str]:
    """Current active G2 stores, from the Datastream landing raw_g2.g2_stores (newest change per store_id, deletes
    dropped; same logic as dbt's cdc_current_state). The internal probe store S999 gets no wheels."""
    sql = f"""
        SELECT store_id FROM `{lake.raw_g2_project}.{lake.raw_g2_dataset}.g2_stores`
        WHERE store_id <> 'S999'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY store_id
                  ORDER BY datastream_metadata.source_timestamp DESC, datastream_metadata.change_sequence_number DESC) = 1
           AND datastream_metadata.change_type != 'DELETE' AND is_active
        ORDER BY store_id"""
    return [r["store_id"] for r in _client(lake).query(sql).result()]


def seed_wheels(lake: LakeSettings, store_ids, seed: int = 42, reset: bool = False) -> int:
    """Load the wheel table once. Refuses a non-empty table unless reset (WRITE_TRUNCATE)."""
    rows = build_wheels(store_ids, seed)
    if not rows:
        raise WheelWriterError("no active stores to put wheels in")
    client = _client(lake)
    has_rows = list(client.query(f"SELECT 1 FROM `{lake.project}.{lake.dataset}.wheel` LIMIT 1").result())
    if has_rows and not reset:
        raise WheelWriterError("wheel is not empty: seed runs once (use --reset to replace the rows)")
    return _load(client, lake, "wheel", rows, "WRITE_TRUNCATE" if reset else "WRITE_APPEND")


def append_events(lake: LakeSettings, rate: float = 1.0, seed: int | None = None, now: datetime | None = None) -> int:
    """One tick: read the active wheel ids, append the events with one load job."""
    client = _client(lake)
    ids = [r["wheel_id"] for r in client.query(
        f"SELECT wheel_id FROM `{lake.project}.{lake.dataset}.wheel` WHERE status = 'ACTIVE' ORDER BY wheel_id").result()]
    rows = generate_events(ids, now or datetime.now(timezone.utc), random.Random(seed), rate)
    return _load(client, lake, "wheel_event", rows, "WRITE_APPEND")
