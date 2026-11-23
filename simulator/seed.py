"""
`seed --batch <folder>`: load the frozen POC 1 batch into an empty G2 database, plus the probe rows (tasks 0.6, A3).

Steps, all or nothing:
1. Check the schema: the 11 tables of sql/g2/schema.sql exist with the expected columns.
2. Refuse if any table has rows (unless --reset on a local database).
3. Rebuild the batch with the vendored generator and check every CSV's MD5 against the baseline manifest.
4. COPY the 9 tables in one transaction; empty strings become NULL, the server casts text to BOOLEAN/TIMESTAMPTZ.
5. Add the probe store and device and the simulator heartbeat.
6. Count every table and compare with baseline.ROWS plus the probe rows.
"""

import base64
import hashlib
import re

from . import baseline
from .db import SCHEMA, upsert_heartbeat
from .vendor import generate_synthetic_data as gen

BATCH_NAME = re.compile(r"^clean_data_\d{8}_\d{6}$")

# Source tables in load order, with their columns: the CSV headers, which are also the G2 column names.
SOURCE_COLUMNS = gen.COLUMNS
EXTRA_TABLES = {
    "store_access": ["principal", "crm_account_id", "granted_at"],
    "heartbeat": ["source", "beat_at"],
}
ALL_TABLES = [*SOURCE_COLUMNS, *EXTRA_TABLES]

PROBE_STORE = {"store_id": baseline.PROBE_STORE_ID, "store_name": "PROBE STORE 999", "brand_id": "B01",
               "location_name": "Internal probe", "country": "US", "is_active": True}
PROBE_DEVICE = {"device_id": baseline.PROBE_DEVICE_ID, "store_id": baseline.PROBE_STORE_ID,
                "installed_location": "MAIN DOOR", "main_door_indicator": True, "device_type": "Door Manager"}
PROBE_ROWS = {"stores": 1, "device_locations": 1, "heartbeat": 1}


class SeedError(Exception):
    pass


def expected_columns():
    cols = {t: [*c, "updated_at"] for t, c in SOURCE_COLUMNS.items()}
    cols.update({t: [*c, "updated_at"] for t, c in EXTRA_TABLES.items()})
    return cols


def check_schema(cur):
    cur.execute(
        "SELECT table_name, array_agg(column_name::text ORDER BY ordinal_position) "
        "FROM information_schema.columns WHERE table_schema = %s GROUP BY table_name",
        (SCHEMA,),
    )
    found = dict(cur.fetchall())
    problems = []
    for table, cols in expected_columns().items():
        if table not in found:
            problems.append(f"g2.{table} is missing")
        elif found[table] != cols:
            problems.append(f"g2.{table} columns {found[table]} != {cols}")
    if problems:
        raise SeedError("Schema check failed (apply sql/g2/schema.sql first):\n  " + "\n  ".join(problems))


def row_counts(cur):
    counts = {}
    for table in ALL_TABLES:
        cur.execute(f"SELECT count(*) FROM {SCHEMA}.{table}")
        counts[table] = cur.fetchone()[0]
    return counts


def build_rows(batch_name):
    """The batch's rows, rebuilt in memory and proven identical to the frozen files."""
    if not BATCH_NAME.match(batch_name):
        raise SeedError(f"--batch must look like clean_data_<yyyymmdd_hhmmss>, not {batch_name!r}")
    if batch_name != baseline.BATCH:
        raise SeedError(f"docs/poc2/baseline.md freezes {baseline.BATCH}; refusing to seed {batch_name}")
    rows = gen.build_clean()
    for table, expected in baseline.MD5.items():
        actual = base64.b64encode(hashlib.md5(gen.render_csv(table, rows[table])).digest()).decode()
        if actual != expected:
            raise SeedError(f"{table}.csv rebuilt with MD5 {actual}, the baseline has {expected}: "
                            "the generator or data-lake-schema version differs from POC 1")
        if len(rows[table]) != baseline.ROWS[table]:
            raise SeedError(f"{table}: {len(rows[table])} rows, the baseline has {baseline.ROWS[table]}")
    return rows


def copy_table(cur, table, columns, rows):
    with cur.copy(f"COPY {SCHEMA}.{table} ({', '.join(columns)}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row([row[c] if row[c] != "" else None for c in columns])


def insert_row(cur, table, row):
    cols = list(row)
    cur.execute(f"INSERT INTO {SCHEMA}.{table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                [row[c] for c in cols])


def seed(conn, batch_name, reset=False, local=False, log=print):
    rows = build_rows(batch_name)
    log(f"Rebuilt {batch_name}: all 9 files match the baseline MD5s")
    with conn.transaction(), conn.cursor() as cur:
        check_schema(cur)
        before = row_counts(cur)
        if any(before.values()):
            if not reset:
                raise SeedError(f"G2 is not empty ({ {t: n for t, n in before.items() if n} }). "
                                "Seed once only; locally, --reset empties it first")
            if not local:
                raise SeedError("--reset is for a local database only: re-seeding Cloud SQL after the stream "
                                "exists sends every old row to raw_g2 as a delete (A3 pitfall)")
            cur.execute(f"TRUNCATE {', '.join(f'{SCHEMA}.{t}' for t in ALL_TABLES)}")
            log("Emptied all 11 tables (--reset)")
        for table, columns in SOURCE_COLUMNS.items():
            copy_table(cur, table, columns, rows[table])
        insert_row(cur, "stores", PROBE_STORE)
        insert_row(cur, "device_locations", PROBE_DEVICE)
        upsert_heartbeat(cur, baseline.HEARTBEAT_SOURCE)
        # store_access rows come from the tenant model in docs/poc2/specs.md (0.7), not written yet.

        after = row_counts(cur)
        expected = {t: baseline.ROWS.get(t, 0) + PROBE_ROWS.get(t, 0) for t in ALL_TABLES}
        if after != expected:
            raise SeedError(f"Row counts {after} != expected {expected}; rolled back")
    for table in ALL_TABLES:
        extra = f" (baseline {baseline.ROWS[table]} + probe)" if table in PROBE_ROWS and table in baseline.ROWS else ""
        log(f"  g2.{table:<17} {after[table]:>5}{extra}")
    log("store_access is empty: its rows come from the tenant model in docs/poc2/specs.md (task 0.7)")
    return after
