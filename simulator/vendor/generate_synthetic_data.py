"""
Generate the synthetic-data uploads for the Data Lake POC, each the 9 CSV source files the ETL tool loads.

There are three kinds of upload, each a folder named <prefix>_<stamp>, where the stamp is the
UTC time to the second, <yyyymmdd_hhmmss>. Only the kind that is asked for is built, and it is
built in memory: build_batch(kind) returns the folder's files as bytes, and upload_batch()
sends them to Cloud Storage without touching the disk. Writing folders to data/ is only for
running it locally (the command line below). Below, <stamp> is the stamp text.

clean_data_<stamp>/ (kind clean): an initial load, all the reference data plus 60 days of incidents
and their history up to the "as of" time, 2026-10-20 00:00 UTC, sized like the
schema doc's synthetic data. Reference values come from the doc's "Lookup
values" section. Every id matches data_lake_schema.formats, every closed list matches
data_lake_schema.enums, every reference resolves, and the incidents and their history
agree with each other, so a run on it rejects no row.

planted_errors_<stamp>/ (kind planted): the same files plus 30 planted errors, one or more per
reject reason the ETL tool's data can trigger. Each uses a
new key, so the upload can be loaded on its own or after the clean one.
Its case list (planted_errors_<stamp>_expected.csv when written locally) gives each error, its file
and line, where it is rejected (INGEST or WAREHOUSE_LOAD) and the reject reason. Two lines at the
end are findings of the clean data too, not planted.

enrichment_<stamp>/ (kind enrichment): the clean files plus 12 incidents with empty store, device,
alert type or alert_id, to try the enrichment of the warehouse load. Six are filled in and
loaded; six cannot be and are rejected. Its case list (enrichment_<stamp>_expected.csv) gives each
case, its line, and what the warehouse should hold or the reject reason. Each incident uses
a new key (INC910701 up, history H0002001 up), so it can be loaded after another upload.

The planted and enrichment folders are both made from the clean data, so the clean data is always
built; the other two are only derived when they are asked for.

Each folder also holds manifest.json, after the CSVs: the batch name, the stamp, and each CSV with
its size and MD5. It is the last file of an upload, so its arrival says the folder is complete.
The case lists are never uploaded.

Deterministic (seed 42): apart from the stamp, the same kind always gives the same bytes.

    python generate_synthetic_data.py                                   # write all three folders to data/
    python generate_synthetic_data.py --kind planted --out /tmp/synthetic    # write only that folder
    python generate_synthetic_data.py --upload clean                    # build clean in memory and upload it
    python generate_synthetic_data.py --upload planted --bucket my-bucket --dry-run

--upload takes clean, planted or enrichment and writes nothing locally. It uploads <bucket>/<folder>/<file>,
the CSVs one by one and manifest.json last, and never overwrites an object. The bucket is --bucket or
the SOURCE_BUCKET variable; credentials are the usual application default credentials. Uploading starts
whatever listens on the bucket.

The headers, formats and allowed values come from the stage models of the data-lake-schema package
(platform-data-lake-poc, packages/data_lake_schema), the same models the ETL tool loads with.
"""

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data_lake_schema import formats
from data_lake_schema.enums import (
    AlertCategory,
    ChangeType,
    DeviceType,
    Priority,
    Severity,
    SystemType,
)
from data_lake_schema.stage import STAGE

OUT = Path(__file__).resolve().parent / "data"  # where the command line writes folders by default
KINDS = {"clean": "clean_data", "planted": "planted_errors", "enrichment": "enrichment"}  # kind -> folder prefix
MANIFEST = "manifest.json"
STAMP_FORMAT = "%Y%m%d_%H%M%S"  # UTC, to the second
SEED = 42
AS_OF = datetime(2026, 10, 20, tzinfo=timezone.utc)
WINDOW_START = AS_OF - timedelta(days=60)
MIN_INCIDENTS = 450

# ---------------------------------------------------------------- reference data

BRANDS = [
    ("B01", "ALPHA FOODS", True, "ALPHA HOLDINGS"),
    ("B02", "ALPHA MARKET", True, "ALPHA HOLDINGS"),
    ("B03", "BETA FRESH", True, "BETA RETAIL GROUP"),
    ("B04", "GAMMA GROCERY", False, "GAMMA RETAIL"),  # no stores
]

TEAMS = [
    ("T01", "Field Service", True),
    ("T02", "Technical Service", True),
    ("T03", "Customer Experience", True),
    ("T04", "Field Service Provider (external)", True),
    ("T05", "Legacy Support", False),
]

NOT_STARTED = "Not Started"
IN_REVIEW = "In Review"
MONITORED = "Alert is being monitored"
CASE_OPENED = "Case Opened"
REOPENED = "Re-Opened"
RESOLVED = "Resolved"
CASE_UPDATED = "Case Updated"

STATUSES = [
    ("0", NOT_STARTED, False, ""),
    ("1", IN_REVIEW, False, "Specialist to review the alert and contact the store"),
    ("2", MONITORED, False, "Keep monitoring; the alert resets to Not Started if still active after 7 days"),
    ("3", CASE_OPENED, False, "Track the service case until a work order is scheduled"),
    ("4", REOPENED, False, "Service case closed but alert still active: review and open a new case"),
    ("5", RESOLVED, True, "Verify resolution"),
    ("6", CASE_UPDATED, False, "Follow up on the latest service-case update"),
]
STATUS_ACTION = {name: action for _, name, _, action in STATUSES}

# id, customer name, description, default priority, active, category, customer category, severity,
# device type, system type, customer facing, internal name, Not Started action
ALERT_TYPES = [
    ("AT01", "Protection Offline", "The door's protection loop is broken, so the exit is not protected.",
     "P1", True, "System Down", "Protection Offline", "Critical", "Door Manager", "Exit", True,
     "Lock Loop Break (3 hours)", "Dispatch a technician"),
    ("AT02", "Device Offline", "The door manager has stopped reporting.",
     "P2", True, "Connectivity", "Device Offline", "Urgent", "Door Manager", "Exit", True,
     "Door Manager Heartbeat Missed (30 minutes)", "Verify / Cycle Power"),
    ("AT03", "Connectivity Offline", "The store's cellular router has lost its connection.",
     "P1", True, "Connectivity", "Connectivity Offline", "Critical", "Cellular Router", "Exit", True,
     "Cellular Link Down (15 minutes)",
     "Check the cellular router and its power; contact the network provider if still offline"),
    ("AT04", "No A/C Power", "The door manager has lost mains power and is running on battery.",
     "P2", True, "System Down", "No A/C Power", "Urgent", "Door Manager", "Exit", True,
     "Mains Power Loss (Battery Backup)", "Ask the store to check the power socket and breaker"),
    ("AT05", "Safety Mode", "The door manager has switched to Safety Mode and is not protecting the exit.",
     "P1", True, "System Down", "Safety Mode", "Critical", "Door Manager", "Exit", True,
     "Safety Mode Engaged", "Ask the store to check the door and reset Safety Mode"),
    ("AT06", "High Wheel Events", "Far more cart wheel events than usual at this door.",
     "P3", True, "General Maintenance", "High Wheel Events", "Warning", "Door Manager", "Containment", True,
     "Wheel Event Count Above Threshold (24 hours)", "Inspect the wheels at this door and schedule wheel service"),
    ("AT07", "No Video Events", "The camera has sent no video events.",
     "P3", True, "Store Activity", "No Video Events", "Warning", "Camera", "Exit", True,
     "Video Event Feed Silent (24 hours)", "Check the camera connection remotely"),
    ("AT08", "Low Wheel Events", "Far fewer cart wheel events than usual at this door.",
     "P4", True, "Store Activity", "Low Wheel Events", "Informational", "Door Manager", "Containment", True,
     "Wheel Event Count Below Threshold (7 days)", "Review cart traffic at this door with the store manager"),
    ("AT09", "Device Disabled", "The door manager's key switch is turned off.",
     "P1", True, "System Down", "Device Disabled", "Store Action Needed", "Door Manager", "Exit", True,
     "Key Switch Off", "Ask the store to turn the key switch back on"),
    ("AT10", "Blocked Camera", "Something is blocking the camera's view.",
     "P3", True, "Other", "Blocked Camera", "Warning", "Camera", "Exit", True,
     "Camera View Obstructed", "Ask the store to clear whatever is blocking the camera's view"),
    ("AT11", "Legacy Temp Sensor Alert", "Retired temperature sensor alert.",
     "P4", False, "Obsolete", "Legacy Sensor", "Warning", "Central Transmitter", "Containment", False,
     "Temperature Sensor Out of Range (Legacy)", "No action needed; retired alert to be reviewed and closed"),
]
AT = {row[0]: row for row in ALERT_TYPES}

# How often each alert type fires, relative to the others. AT11 is retired: it never fires.
AT_WEIGHTS = {"AT01": 15, "AT02": 15, "AT03": 10, "AT04": 10, "AT05": 8, "AT06": 10,
              "AT07": 8, "AT08": 10, "AT09": 6, "AT10": 5}

# country, region (level_1), division (level_2), district (level_3), state, city
PLACES = [
    ("US", "West", "West Division", "101", "CA", "Sacramento"),
    ("US", "West", "West Division", "102", "CA", "San Diego"),
    ("US", "Southwest", "Central Division", "201", "TX", "Austin"),
    ("US", "Northeast", "East Division", "301", "NY", "Albany"),
    ("CA", "Central", "Canada Division", "401", "ON", "Toronto"),
    ("CA", "West", "Canada Division", "402", "BC", "Vancouver"),
    ("GB", "North", "UK Division", "501", "ENG", "Leeds"),
    ("GB", "North", "UK Division", "502", "SCT", "Glasgow"),
    ("IE", "Ireland", "UK Division", "601", "L", "Dublin"),
]

SIDE_DOORS = ["PHARMACY DOOR", "CUSTOMER SERVICE DOOR", "FLORAL DOOR", "DELI DOOR", "SELF CHECKOUT DOOR",
              "GM DOOR", "PRODUCE DOOR", "CAFE DOOR", "BAKERY DOOR"]

COMMENTS = [
    "Called the store; the manager is checking the door.",
    "Store confirmed the door is closed and clear.",
    "Remote reset attempted; waiting for the device to report.",
    "Technician booked for the next business day.",
    "Work order created with the service provider.",
    "Store reports construction work near the door.",
    "Spoke to the store; power strip was switched off by cleaners.",
    "Parts on order; technician will return to finish the repair.",
]


# ---------------------------------------------------------------- builders

def build_users(rng):
    # (prefix, team, count): role-style names, @example.com addresses.
    plan = [("Field Specialist", "T01", 5), ("Technical Specialist", "T02", 4),
            ("Customer Experience Agent", "T03", 4), ("Service Provider Technician", "T04", 3),
            ("Legacy Support Analyst", "T05", 2)]
    users, n = [], 0
    for role, team, count in plan:
        for i in range(1, count + 1):
            n += 1
            name = f"{role} {i:02d}"
            email = f"{name.lower().replace(' ', '.')}@example.com"
            users.append((f"U{n:03d}", name, email, team, team != "T05"))
    return users


def build_stores():
    stores = []
    for i in range(40):
        number = 101 + i
        brand_id, brand_name = BRANDS[i % 3][:2]
        country, region, division, district, state, city = PLACES[i % len(PLACES)]
        stores.append((f"S{number}", f"{brand_name} {number}", brand_id, city, division, region,
                       country, state, district, True))
    return stores


def build_devices(rng, stores):
    """Every store has a main-door manager and a router; some have side doors, cameras and more."""
    devices = []

    def add(store_id, location, main, device_type):
        devices.append((f"D{len(devices) + 1:03d}", store_id, location, main, device_type))

    for i, store in enumerate(stores):
        sid = store[0]
        # Every 7th store's main exit is the grocery entrance: a main exit without MAIN in its name.
        add(sid, "GROCERY ENTRANCE DOOR" if i % 7 == 3 else "MAIN DOOR", True, "Door Manager")
        if i % 3 != 2:
            add(sid, rng.choice(SIDE_DOORS), False, "Door Manager")
        add(sid, "SYSTEM", False, "Cellular Router")
        if i % 2 == 0:
            add(sid, "MAIN DOOR", True, "Camera")
        if i % 20 == 4:
            add(sid, "STOCK ROOM", False, "Central Transmitter")
        if i % 13 == 6:
            add(sid, "SYSTEM", False, "POE Switch")
    return devices


def ts(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def minutes(rng, low, high):
    return timedelta(minutes=rng.randint(low, high))


def plan_events(rng):
    """
    One incident's life as (delay, change_type, previous, new, by_user, comment), from CREATED on.

    by_user True means the assignee made the change; system events have no user.
    """
    steps = [(timedelta(0), "CREATED", None, NOT_STARTED, False, None)]
    if rng.random() < 0.45:  # Alert clears by itself before anyone picks it up.
        steps.append((minutes(rng, 10, 360), "RESOLVED", NOT_STARTED, RESOLVED, False, None))
        return steps

    # Usually picked up within hours; sometimes the queue is backed up for days.
    pickup = minutes(rng, 1440, 5760) if rng.random() < 0.15 else minutes(rng, 5, 180)
    steps.append((pickup, "ASSIGNED", NOT_STARTED, IN_REVIEW, True, None))
    status = IN_REVIEW
    path = rng.random()
    if path < 0.3:  # Reviewed and cleared.
        if rng.random() < 0.5:
            steps.append((minutes(rng, 15, 600), "COMMENT", None, None, True, rng.choice(COMMENTS)))
    elif path < 0.55:  # Watched for a while.
        steps.append((minutes(rng, 30, 720), "STATUS_CHANGED", status, MONITORED, True, None))
        status = MONITORED
        if rng.random() < 0.3:  # Still active after 7 days: back to Not Started and picked up again.
            steps.append((timedelta(days=7), "MONITORING_TIMEOUT", MONITORED, NOT_STARTED, False, None))
            steps.append((minutes(rng, 10, 240), "ASSIGNED", NOT_STARTED, IN_REVIEW, True, None))
            steps.append((minutes(rng, 60, 1440), "STATUS_CHANGED", IN_REVIEW, CASE_OPENED, True, None))
            status = CASE_OPENED
    else:  # A service case is opened.
        steps.append((minutes(rng, 30, 720), "STATUS_CHANGED", status, CASE_OPENED, True, None))
        status = CASE_OPENED
        if rng.random() < 0.4:
            steps.append((minutes(rng, 60, 1440), "COMMENT", None, None, True, rng.choice(COMMENTS)))
        if rng.random() < 0.5:
            steps.append((minutes(rng, 600, 4320), "STATUS_CHANGED", status, CASE_UPDATED, True, None))
            status = CASE_UPDATED
        if rng.random() < 0.2:  # Case closed, alert still active.
            steps.append((minutes(rng, 600, 2880), "REOPENED", status, REOPENED, False, None))
            steps.append((minutes(rng, 30, 600), "STATUS_CHANGED", REOPENED, CASE_OPENED, True, None))
            status = CASE_OPENED
    steps.append((minutes(rng, 60, 4320), "RESOLVED", status, RESOLVED, False, None))
    return steps


def build_incidents(rng, stores, devices, users):
    brand_of = {s[0]: s[2] for s in stores}
    devices_by_type = {}
    for device in devices:
        devices_by_type.setdefault(device[4], []).append(device)
    assignees = [u for u in users if u[4] and u[3] in ("T01", "T02", "T03", "T04")]
    assignee_weights = [1 if u[3] == "T04" else 3 for u in assignees]

    type_ids = list(AT_WEIGHTS)
    incidents, streams = [], set()
    while len(incidents) < MIN_INCIDENTS:
        at_id = rng.choices(type_ids, weights=[AT_WEIGHTS[t] for t in type_ids])[0]
        device = rng.choice(devices_by_type[AT[at_id][8]])  # The device is of the type the alert comes from.
        alert_id = f"ALR-{device[0]}-{at_id}"
        if alert_id in streams:
            continue
        streams.add(alert_id)

        # A quarter of the streams start in the last 10 days, so the data has current issues.
        first = AS_OF - timedelta(days=10) if rng.random() < 0.25 else WINDOW_START
        start = first + timedelta(seconds=rng.randint(0, int((AS_OF - first).total_seconds()) - 3600))
        for _ in range(rng.choice([1, 1, 1, 2, 2, 3, 4])):  # Re-fires of the same stream never overlap.
            if start >= AS_OF:
                break
            incident = simulate(rng, at_id, device, brand_of, start, assignees, assignee_weights)
            incidents.append(incident)
            if incident["resolved"] is None:
                break
            start = incident["resolved"] + minutes(rng, 600, 14400)
    return incidents


def simulate(rng, at_id, device, brand_of, alert_time, assignees, assignee_weights):
    """Play the planned events forward; whatever would happen after "as of" hasn't happened yet."""
    priority = AT[at_id][3]
    if rng.random() < 0.15:
        priority = rng.choice([p.value for p in Priority])
    user = rng.choices(assignees, weights=assignee_weights)[0][0]

    events, t, status, assigned = [], alert_time, None, None
    steps = plan_events(rng)
    # Some cases are still being worked: not resolved yet, however old (never a monitored alert, which
    # times out after 7 days).
    if len(steps) > 2 and steps[-1][2] != MONITORED and rng.random() < 0.1:
        steps = steps[:-1]
    for delay, change_type, previous, new, by_user, comment in steps:
        t = t + delay
        if t >= AS_OF:
            break
        if change_type == "ASSIGNED":
            assigned = user
        events.append({"time": t, "type": change_type, "previous": previous, "new": new,
                       "user": user if by_user else None, "comment": comment})
        if new is not None:
            status = new

    return {
        "alert_id": f"ALR-{device[0]}-{at_id}",
        "store_id": device[1],
        "alert_type_id": at_id,
        "brand_id": brand_of[device[1]],
        "assigned_user_id": assigned,
        "device_id": device[0],
        "location_name": device[2],
        "next_step_action": AT[at_id][12] if status == NOT_STARTED else STATUS_ACTION[status],
        "created": alert_time,
        "resolved": events[-1]["time"] if status == RESOLVED else None,
        "current_status": status,
        "priority": priority,
        "events": events,
    }


# ---------------------------------------------------------------- source files

# Source columns of each stage table, in order: the CSV header of its file.
COLUMNS = {
    model.__table_config__.name: [field for field, info in model.model_fields.items() if not info.alias]
    for model in STAGE.tables
}
EXTRA = "_extra"  # Fields written after a row's columns: makes a malformed line.


def flag(value):
    return "true" if value else "false"


def parse(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def build_files(users, stores, devices, incidents):
    """The 9 source files as rows of text keyed by source column; an empty string is an empty value."""
    for i, incident in enumerate(incidents):
        incident["incident_id"] = f"INC{910101 + i:06d}"
    events = sorted(
        ((e, inc) for inc in incidents for e in inc["events"]), key=lambda x: (x[0]["time"], x[1]["incident_id"])
    )
    return {
        "brands": [{"brand_id": b, "brand_name": n, "is_active": flag(a), "ultimate_parent": p}
                   for b, n, a, p in BRANDS],
        "teams": [{"team_id": t, "team_name": n, "is_active": flag(a)} for t, n, a in TEAMS],
        "statuses": [{"status_id": i, "status_name": n, "is_closed": flag(c), "next_step_action": a}
                     for i, n, c, a in STATUSES],
        "alert_types": [
            {"alert_type_id": a[0], "alert_type_name": a[1], "description": a[2], "default_priority": a[3],
             "is_active": flag(a[4]), "category_name": a[5], "customer_category_name": a[6], "severity": a[7],
             "device_type": a[8], "system_type": a[9], "customer_facing": flag(a[10]),
             "internal_alert_name": a[11], "not_started_next_step_action": a[12]}
            for a in ALERT_TYPES
        ],
        "users": [{"user_id": u, "user_name": n, "email": e, "team_id": t, "is_active": flag(a)}
                  for u, n, e, t, a in users],
        "stores": [store_row(s[0], s[1], s[2], s[3:9], s[9]) for s in stores],
        "device_locations": [{"device_id": d, "store_id": s, "installed_location": loc,
                              "main_door_indicator": flag(main), "device_type": t}
                             for d, s, loc, main, t in devices],
        "alert_incidents": [
            {
                "incident_id": inc["incident_id"],
                "alert_id": inc["alert_id"],
                "store_id": inc["store_id"],
                "alert_type_id": inc["alert_type_id"],
                "brand_id": inc["brand_id"],
                "assigned_user_id": inc["assigned_user_id"] or "",
                "device_id": inc["device_id"],
                "location_name": inc["location_name"],
                "next_step_action": inc["next_step_action"],
                "created_at": ts(inc["created"]),
                "resolved_at": ts(inc["resolved"]) if inc["resolved"] else "",
                "current_status": inc["current_status"],
                "priority": inc["priority"],
            }
            for inc in incidents
        ],
        "alert_history": [
            {
                "history_id": f"H{n:07d}",
                "incident_id": inc["incident_id"],
                "event_timestamp": ts(e["time"]),
                "event_type": e["type"],
                "previous_status": e["previous"] or "",
                "new_status": e["new"] or "",
                "changed_by_user_id": e["user"] or "",
                "comments": e["comment"] or "",
            }
            for n, (e, inc) in enumerate(events, start=1)
        ],
    }


def store_row(store_id, name, brand_id, place, active):
    """A stores.csv row; place = (city, division, region, country, state, district)."""
    city, division, region, country, state, district = place
    return {"store_id": store_id, "store_name": name, "brand_id": brand_id, "location_name": city,
            "department": division, "region": region, "country": country, "state": state, "district": district,
            "is_active": flag(active) if isinstance(active, bool) else active}


def render_csv(name, rows):
    """One source file as UTF-8 bytes: its stage table's header, then a line per row (\\n line endings)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS[name])
    for row in rows:
        writer.writerow([row[column] for column in COLUMNS[name]] + row.get(EXTRA, []))
    return buffer.getvalue().encode("utf-8")


def render_table(header, rows):
    """A small CSV (a case list) as UTF-8 bytes."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


# ---------------------------------------------------------------- planted errors

def plant_errors(clean):
    """
    The clean files plus 30 planted errors, and the expected result of each.

    Every planted row has a key the clean files don't use, so this upload gives the same results
    loaded on its own or after the clean one.
    """
    rng = random.Random(SEED + 1)
    files = {name: [dict(row) for row in rows] for name, rows in clean.items()}
    store_brand = {s["store_id"]: s["brand_id"] for s in files["stores"]}
    devices = files["device_locations"]
    streams = {i["alert_id"] for i in files["alert_incidents"]}
    assignees = [u["user_id"] for u in files["users"] if u["is_active"] == "true" and u["team_id"] in ("T01", "T02")]
    worked = [i for i in files["alert_incidents"]
              if i["resolved_at"] and parse(i["resolved_at"]) - parse(i["created_at"]) >= timedelta(hours=2)]
    hosts = iter(rng.sample(worked, 4))  # Clean incidents that get a planted history event.
    incident_ids = iter(range(910101 + len(files["alert_incidents"]), 999999))
    history_ids = iter(range(len(files["alert_history"]) + 1, 9999999))
    added = {name: [] for name in files}
    orders = []  # (table, row that must come first, row that must come later)
    errors = []

    def plant(table, row, column, planted, caught_at, expected):
        added[table].append(row)
        errors.append({"table": table, "row": row, "column_name": column, "planted": planted,
                       "caught_at": caught_at, "expected": expected})
        return row

    def mark(table, row, column, planted, caught_at, expected):
        """An error on a row that is already in the files (added as a support row)."""
        errors.append({"table": table, "row": row, "column_name": column, "planted": planted,
                       "caught_at": caught_at, "expected": expected})

    def support(table, row):
        """A valid row a planted error needs."""
        added[table].append(row)
        return row

    def when(k):
        return datetime(2026, 10, 1, 9, tzinfo=timezone.utc) + timedelta(hours=10 * k)

    def device_for(device_type, at_id):
        """A device of the type, whose stream with the alert type has never fired."""
        for d in rng.sample(devices, len(devices)):
            alert_id = f"ALR-{d['device_id']}-{at_id}"
            if d["device_type"] == device_type and alert_id not in streams:
                streams.add(alert_id)
                return d
        raise AssertionError(f"no free {device_type} for {at_id}")

    def incident(device, at_id, created, status, *, resolved=None, user="", store=None, brand=None,
                 priority=None):
        store = store or device["store_id"]
        known = at_id in AT
        return {
            "incident_id": f"INC{next(incident_ids):06d}",
            "alert_id": f"ALR-{device['device_id']}-{at_id}",
            "store_id": store,
            "alert_type_id": at_id,
            "brand_id": store_brand.get(store, "") if brand is None else brand,
            "assigned_user_id": user,
            "device_id": device["device_id"],
            "location_name": device["installed_location"],
            "next_step_action": (AT[at_id][12] if status == NOT_STARTED else STATUS_ACTION[status]) if known else "",
            "created_at": ts(created),
            "resolved_at": ts(resolved) if resolved else "",
            "current_status": status,
            "priority": priority or (AT[at_id][3] if known else "P2"),
        }

    def event(incident_id, at, change_type, previous="", new="", user="", comment=""):
        return {"history_id": f"H{next(history_ids):07d}", "incident_id": incident_id, "event_timestamp": ts(at),
                "event_type": change_type, "previous_status": previous, "new_status": new,
                "changed_by_user_id": user, "comments": comment}

    def history(inc, *steps):
        """Events for a planted incident: (minutes after it fired, type, previous, new, by the assignee). Returns them."""
        return [
            support("alert_history", event(inc["incident_id"], parse(inc["created_at"]) + timedelta(minutes=offset),
                                           change_type, previous, new, inc["assigned_user_id"] if by_user else ""))
            for offset, change_type, previous, new, by_user in steps
        ]

    def on_clean(change_type, previous="", new="", user=None, comment=""):
        """A new event on a clean, worked incident, an hour after it fired."""
        host = next(hosts)
        return event(host["incident_id"], parse(host["created_at"]) + timedelta(hours=1), change_type, previous,
                     new, user or host["assigned_user_id"] or rng.choice(assignees), comment)

    created = ((0, "CREATED", "", NOT_STARTED, False),)
    opened = created + ((20, "ASSIGNED", NOT_STARTED, IN_REVIEW, True),)
    worked_life = opened + ((180, "RESOLVED", IN_REVIEW, RESOLVED, False),)

    def resolved_at(k):
        return when(k) + timedelta(minutes=180)

    place = (PLACES[2][5], PLACES[2][2], PLACES[2][1], PLACES[2][0], PLACES[2][4], PLACES[2][3])

    # Ingest: the file contract.
    inc = incident(device_for("Door Manager", "AT02"), "AT02", when(0), RESOLVED, resolved=resolved_at(0),
                   user=rng.choice(assignees))
    inc["incident_id"] = ""
    plant("alert_incidents", inc, "incident_id", "Empty incident_id, the file's key", "INGEST", "MISSING_REQUIRED")
    row = on_clean("COMMENT", comment="Store called back")
    row[EXTRA] = [" door fixed"]
    plant("alert_history", row, "", "Comment with an unquoted comma: one field too many", "INGEST", "BAD_CSV")

    # Warehouse load: types, formats, required values, allowed values, duplicates.
    plant("device_locations", {"device_id": "DEV200", "store_id": "S101", "installed_location": "DELI DOOR",
                               "main_door_indicator": "false", "device_type": "Door Manager"},
          "device_id", "Device id DEV200 is not D + 3 digits", "WAREHOUSE_LOAD", "BAD_PATTERN")
    plant("users", {"user_id": "U021", "user_name": "Field Specialist 06", "email": "", "team_id": "T01",
                    "is_active": "true"},
          "email", "Empty email", "WAREHOUSE_LOAD", "MISSING_REQUIRED")
    inc = incident(device_for("Door Manager", "AT06"), "AT06", when(1), RESOLVED, resolved=resolved_at(1),
                   user=rng.choice(assignees), priority="P9")
    plant("alert_incidents", inc, "priority", "Priority P9 is not P1-P5", "WAREHOUSE_LOAD", "BAD_ENUM")
    plant("alert_history", on_clean("STATUS_CHANGED", IN_REVIEW, "Closed"),
          "new_status", "Status text Closed is not in statuses.csv", "WAREHOUSE_LOAD", "BAD_ENUM")
    plant("stores", store_row("S144", "BETA FRESH 144", "B03", place, "yes"),
          "is_active", "is_active is yes, not true or false", "WAREHOUSE_LOAD", "BAD_TYPE")
    inc = incident(device_for("Cellular Router", "AT03"), "AT03", when(2), RESOLVED, resolved=resolved_at(2),
                   user=rng.choice(assignees))
    inc["resolved_at"] = resolved_at(2).strftime("%Y/%m/%d %H:%M")
    plant("alert_incidents", inc, "resolved_at", f"resolved_at {inc['resolved_at']} is not a UTC time like "
          "2026-10-18T06:00:00Z", "WAREHOUSE_LOAD", "BAD_TIMESTAMP")
    first = support("alert_history", on_clean("COMMENT", comment="Store asked when the technician will arrive."))
    copy = plant("alert_history", dict(first), "", "The same line twice; the second copy is rejected",
                 "WAREHOUSE_LOAD", "DUPLICATE_EXACT")
    orders.append(("alert_history", first, copy))
    kept = support("stores", store_row("S145", "BETA FRESH 145", "B03", place, True))
    older = plant("stores", dict(kept, store_name="BETA FRESH 145 OLD"), "store_name",
                  "Store S145 twice with different names; the first row is rejected, the last kept",
                  "WAREHOUSE_LOAD", "DUPLICATE_KEY_CONFLICT")
    orders.append(("stores", older, kept))
    at13 = plant("alert_types", dict(files["alert_types"][1], alert_type_id="AT13",
                                     internal_alert_name="Door Manager Heartbeat Missed (2 hours)"),
                 "alert_type_name", "Customer name Device Offline is already AT02's; AT02 is kept",
                 "WAREHOUSE_LOAD", "DUPLICATE_UNIQUE")
    orders.append(("alert_types", files["alert_types"][1], at13))

    # Data quality: loaded, then reported.
    plant("stores", store_row("S141", "DELTA FOODS 141", "B09", place, False),
          "brand_id", "Brand B09 is not in brands.csv (inactive store)", "WAREHOUSE_LOAD", "UNKNOWN_REFERENCE")
    plant("users", {"user_id": "U019", "user_name": "Field Specialist 07",
                    "email": "field.specialist.07@example.com", "team_id": "T09", "is_active": "true"},
          "team_id", "Team T09 is not in teams.csv", "WAREHOUSE_LOAD", "UNKNOWN_REFERENCE")
    plant("users", {"user_id": "U020", "user_name": "Customer Experience Agent 05",
                    "email": "customer.experience.agent.05@example.com", "team_id": "", "is_active": "true"},
          "team_id", "Active user with no team", "WAREHOUSE_LOAD", "MISSING_REQUIRED")
    lost = plant("device_locations", {"device_id": f"D{len(devices) + 1:03d}", "store_id": "S198",
                                      "installed_location": "MAIN DOOR", "main_door_indicator": "true",
                                      "device_type": "Door Manager"},
                 "store_id", "Store S198 is not in stores.csv", "WAREHOUSE_LOAD", "UNKNOWN_REFERENCE")
    streams.add(f"ALR-{lost['device_id']}-AT01")
    inc = incident(lost, "AT01", when(3), RESOLVED, resolved=resolved_at(3), user=rng.choice(assignees), brand="")
    plant("alert_incidents", inc, "store_id", "Store S198 is not in stores.csv", "WAREHOUSE_LOAD", "UNKNOWN_REFERENCE")
    history(inc, *worked_life)
    inc = incident(device_for("Door Manager", "AT12"), "AT12", when(4), RESOLVED, resolved=resolved_at(4),
                   user=rng.choice(assignees))
    plant("alert_incidents", inc, "alert_type_id", "Alert type AT12 is not in alert_types.csv, and the incident "
          "has no history", "WAREHOUSE_LOAD", "UNKNOWN_REFERENCE")
    unknown = {"device_id": "D999", "store_id": "S106", "installed_location": "MAIN DOOR"}
    inc = incident(unknown, "AT02", when(5), RESOLVED, resolved=resolved_at(5), user=rng.choice(assignees))
    plant("alert_incidents", inc, "device_id", "Device D999 is not in device_locations.csv", "WAREHOUSE_LOAD", "UNKNOWN_REFERENCE")
    history(inc, *worked_life)
    device = device_for("Door Manager", "AT05")
    elsewhere = rng.choice([s for s in files["stores"] if s["store_id"] != device["store_id"]])["store_id"]
    inc = incident(device, "AT05", when(6), RESOLVED, resolved=resolved_at(6), user=rng.choice(assignees),
                   store=elsewhere)
    plant("alert_incidents", inc, "device_id", f"Device {device['device_id']} is installed at "
          f"{device['store_id']}, not at {elsewhere}", "WAREHOUSE_LOAD", "INCONSISTENT_VALUE")
    history(inc, *worked_life)
    device = device_for("Door Manager", "AT04")
    wrong = next(b for b in ("B01", "B02", "B03") if b != store_brand[device["store_id"]])
    inc = incident(device, "AT04", when(7), RESOLVED, resolved=resolved_at(7), user=rng.choice(assignees),
                   brand=wrong)
    plant("alert_incidents", inc, "brand_id", f"Brand {wrong} is not the brand of store {device['store_id']}",
          "WAREHOUSE_LOAD", "INCONSISTENT_VALUE")
    history(inc, *worked_life)
    inc = incident(device_for("Door Manager", "AT09"), "AT09", when(8), RESOLVED, resolved=resolved_at(8),
                   user="U099")
    plant("alert_incidents", inc, "assigned_user_id", "Assigned user U099 is not in users.csv", "WAREHOUSE_LOAD",
          "UNKNOWN_REFERENCE")
    history(inc, *created, (20, "ASSIGNED", NOT_STARTED, IN_REVIEW, False), (180, "RESOLVED", IN_REVIEW, RESOLVED,
                                                                           False))
    inc = incident(device_for("Door Manager", "AT08"), "AT08", when(9), RESOLVED,
                   resolved=when(9) - timedelta(hours=2), user=rng.choice(assignees))
    plant("alert_incidents", inc, "resolved_at", "Resolved 2 hours before it fired", "WAREHOUSE_LOAD", "INCONSISTENT_VALUE")
    history(inc, *worked_life)
    inc = incident(device_for("Door Manager", "AT01"), "AT01", datetime(2027, 1, 15, 8, tzinfo=timezone.utc),
                   NOT_STARTED)
    plant("alert_incidents", inc, "created_at", "Fired 2027-01-15, after the as-of time; so is its CREATED event",
          "WAREHOUSE_LOAD", "INCONSISTENT_VALUE")
    history(inc, *created)
    inc = incident(device_for("Door Manager", "AT02"), "AT02", when(10), RESOLVED, user=rng.choice(assignees))
    plant("alert_incidents", inc, "resolved_at", "Status Resolved, but no resolved_at", "WAREHOUSE_LOAD", "INCONSISTENT_VALUE")
    history(inc, *worked_life)
    plant("stores", store_row("S142", "ALPHA FOODS 142", "B01", place[:2] + ("",) + place[3:], True),
          "region", "Active store with no region", "WAREHOUSE_LOAD", "MISSING_REQUIRED")
    plant("alert_history", event("INC999999", when(11), "COMMENT", user=rng.choice(assignees),
                                 comment="Following up with the store."),
          "incident_id", "Incident INC999999 is not in alert_incidents.csv", "WAREHOUSE_LOAD", "UNKNOWN_REFERENCE")
    plant("alert_history", on_clean("COMMENT", user="U098", comment="Checked the door camera remotely."),
          "changed_by_user_id", "User U098 is not in users.csv", "WAREHOUSE_LOAD", "UNKNOWN_REFERENCE")
    support("stores", store_row("S143", "ALPHA MARKET 143", "B02", place, False))
    closed_store = support("device_locations", {"device_id": f"D{len(devices) + 2:03d}", "store_id": "S143",
                                                "installed_location": "MAIN DOOR", "main_door_indicator": "true",
                                                "device_type": "Door Manager"})
    inc = incident(closed_store, "AT01", when(12), IN_REVIEW, user=rng.choice(assignees))
    plant("alert_incidents", inc, "store_id", "Open incident at store S143, which is inactive", "WAREHOUSE_LOAD",
          "INCONSISTENT_VALUE")
    history(inc, *opened)
    inc = incident(device_for("Door Manager", "AT06"), "AT06", when(13), CASE_OPENED, user=rng.choice(assignees))
    support("alert_incidents", inc)
    last = history(inc, *opened)[-1]
    mark("alert_history", last, "new_status", f"The last status event moves {inc['incident_id']} to In Review, but "
         "the incident has status Case Opened; the event is rejected", "WAREHOUSE_LOAD", "INCONSISTENT_VALUE")
    device = device_for("Door Manager", "AT02")
    still_open = incident(device, "AT02", when(14), IN_REVIEW, user=rng.choice(assignees))
    support("alert_incidents", still_open)
    history(still_open, *opened)
    inc = incident(device, "AT02", when(18), RESOLVED, resolved=resolved_at(18), user=rng.choice(assignees))
    plant("alert_incidents", inc, "alert_id", f"Stream {inc['alert_id']} fires again while "
          f"{still_open['incident_id']} is still open", "WAREHOUSE_LOAD", "INCONSISTENT_VALUE")
    history(inc, *worked_life)
    assert len(errors) == 30, len(errors)

    # Scatter the new rows through the files, keeping each pair in the order its rule needs.
    for table, rows in added.items():
        for row in rows:
            files[table].insert(rng.randint(0, len(files[table])), row)
    for table, earlier, later in orders:
        rows = files[table]
        i, j = index_of(rows, earlier), index_of(rows, later)
        if i > j:
            rows[i], rows[j] = rows[j], rows[i]
    return files, errors


def index_of(rows, row):
    return next(n for n, r in enumerate(rows) if r is row)


def render_expected(files, errors, baseline):
    """The planted-error list: where each error is and what should catch it."""
    rows = [[n, f"{e['table']}.csv", index_of(files[e["table"]], e["row"]) + 2, e["row"][COLUMNS[e["table"]][0]],
             e["column_name"], e["planted"], e["caught_at"], e["expected"]] for n, e in enumerate(errors, start=1)]
    rows += [["", "", "", *row] for row in baseline]
    print(f"planted: {len(errors)} planted errors, {len(baseline)} baseline findings")
    return render_table(["error_no", "file", "line_no", "record_key", "column_name", "planted", "caught_at",
                         "expected"], rows)


# ---------------------------------------------------------------- checks

FORMATS = [
    ("brands", "brand_id", formats.BRAND_ID), ("teams", "team_id", formats.TEAM_ID),
    ("statuses", "status_id", formats.STATUS_ID), ("alert_types", "alert_type_id", formats.ALERT_TYPE_ID),
    ("users", "user_id", formats.USER_ID), ("users", "email", formats.EMAIL), ("users", "team_id", formats.TEAM_ID),
    ("stores", "store_id", formats.STORE_ID), ("stores", "brand_id", formats.BRAND_ID),
    ("device_locations", "device_id", formats.DEVICE_ID), ("device_locations", "store_id", formats.STORE_ID),
    ("alert_incidents", "incident_id", formats.INCIDENT_ID), ("alert_incidents", "alert_id", formats.ALERT_STREAM_ID),
    ("alert_incidents", "store_id", formats.STORE_ID), ("alert_incidents", "device_id", formats.DEVICE_ID),
    ("alert_incidents", "alert_type_id", formats.ALERT_TYPE_ID),
    ("alert_incidents", "assigned_user_id", formats.USER_ID), ("alert_incidents", "brand_id", formats.BRAND_ID),
    ("alert_history", "history_id", formats.HISTORY_EVENT_ID), ("alert_history", "incident_id", formats.INCIDENT_ID),
    ("alert_history", "changed_by_user_id", formats.USER_ID),
]
ALLOWED = [
    ("alert_types", "default_priority", Priority), ("alert_types", "category_name", AlertCategory),
    ("alert_types", "severity", Severity), ("alert_types", "device_type", DeviceType),
    ("alert_types", "system_type", SystemType), ("device_locations", "device_type", DeviceType),
    ("alert_incidents", "priority", Priority), ("alert_history", "event_type", ChangeType),
]
BOOLS = [("brands", "is_active"), ("teams", "is_active"), ("statuses", "is_closed"), ("alert_types", "is_active"),
         ("alert_types", "customer_facing"), ("users", "is_active"), ("stores", "is_active"),
         ("device_locations", "main_door_indicator")]
TIMES = [("alert_incidents", "created_at"), ("alert_incidents", "resolved_at"), ("alert_history", "event_timestamp")]
# Source columns that may be empty in clean data; every other value is filled in.
OPTIONAL = {("statuses", "next_step_action"),
            ("alert_incidents", "assigned_user_id"), ("alert_incidents", "resolved_at"),
            ("alert_history", "previous_status"), ("alert_history", "new_status"),
            ("alert_history", "changed_by_user_id"), ("alert_history", "comments")}
UNIQUE = [("brands", "brand_name"), ("teams", "team_name"), ("statuses", "status_name"), ("users", "email"),
          ("alert_types", "alert_type_name"), ("alert_types", "internal_alert_name")]


def validate_clean(files):
    """The checks a clean run relies on: formats, types, allowed values, required, unique, references, consistency."""
    for table, column in [(t, c) for t in files for c in COLUMNS[t] if (t, c) not in OPTIONAL]:
        assert all(r[column] for r in files[table]), f"{table}.{column} has an empty value"
    for table, column, pattern in FORMATS:
        bad = [r[column] for r in files[table] if r[column] and not re.match(pattern, r[column])]
        assert not bad, f"{table}.{column}: {bad[:5]} do not match {pattern}"
    for table, column, enum in ALLOWED:
        assert {r[column] for r in files[table]} <= {m.value for m in enum}, f"{table}.{column}"
    for table, column in BOOLS:
        assert {r[column] for r in files[table]} <= {"true", "false"}, f"{table}.{column}"
    for table, column in TIMES:
        bad = [r[column] for r in files[table] if r[column] and not re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$",
                                                                              r[column])]
        assert not bad, f"{table}.{column}: {bad[:5]}"
    for table, column in [(t, COLUMNS[t][0]) for t in files] + UNIQUE:
        values = [r[column] for r in files[table]]
        assert len(values) == len(set(values)), f"{table}.{column} repeats"
    assert all("\n" not in v for rows in files.values() for r in rows for v in r.values())

    teams, brands = {t["team_id"] for t in files["teams"]}, {b["brand_id"] for b in files["brands"]}
    users = {u["user_id"]: u for u in files["users"]}
    active_users = {u for u, row in users.items() if row["is_active"] == "true"}
    stores = {s["store_id"]: s for s in files["stores"]}
    devices = {d["device_id"]: d for d in files["device_locations"]}
    types = {a["alert_type_id"]: a for a in files["alert_types"]}
    statuses = {s["status_name"]: s for s in files["statuses"]}
    assert all(u["team_id"] in teams for u in users.values()), "DQ02/DQ03"
    assert all(s["brand_id"] in brands for s in stores.values()), "DQ01"
    assert all(d["store_id"] in stores for d in devices.values()), "DQ04"

    by_incident = {}
    for h in files["alert_history"]:
        by_incident.setdefault(h["incident_id"], []).append(h)
        assert h["previous_status"] in statuses.keys() | {""} and h["new_status"] in statuses.keys() | {""}
        assert h["changed_by_user_id"] in active_users | {""}, "DQ19"
        assert h["event_timestamp"] < ts(AS_OF), "DQ27"
    assert set(by_incident) <= {i["incident_id"] for i in files["alert_incidents"]}, "DQ18"

    windows = {}
    for inc in files["alert_incidents"]:
        d, status = devices[inc["device_id"]], statuses[inc["current_status"]]
        assert inc["store_id"] in stores and inc["alert_type_id"] in types, "DQ05/DQ06"
        assert types[inc["alert_type_id"]]["is_active"] == "true", "only active alert types fire"
        assert d["store_id"] == inc["store_id"], "DQ08"
        assert d["device_type"] == types[inc["alert_type_id"]]["device_type"], "DQ34"
        assert stores[inc["store_id"]]["brand_id"] == inc["brand_id"], "DQ09"
        assert inc["assigned_user_id"] in active_users | {""}, "DQ10/DQ30"
        assert inc["created_at"] < ts(AS_OF) and inc["resolved_at"] < ts(AS_OF), "DQ12"
        assert (status["is_closed"] == "true") == bool(inc["resolved_at"]), "DQ13"
        assert not inc["resolved_at"] or inc["resolved_at"] >= inc["created_at"], "DQ11"
        assert status["next_step_action"] or types[inc["alert_type_id"]]["not_started_next_step_action"], "DQ14"
        events = by_incident[inc["incident_id"]]  # DQ20: every incident has history
        assert events[0]["event_type"] == "CREATED" and events[0]["event_timestamp"] == inc["created_at"]
        assert all(e["event_timestamp"] >= inc["created_at"] for e in events), "DQ27"
        assert [e for e in events if e["new_status"]][-1]["new_status"] == inc["current_status"], "DQ28"
        windows.setdefault(inc["alert_id"], []).append((inc["created_at"], inc["resolved_at"] or "9999"))
    for spans in windows.values():
        spans.sort()
        assert all(a[1] < b[0] for a, b in zip(spans, spans[1:])), "DQ29"


def validate_batch(batch, files):
    """The batch is exactly the 9 files then the manifest; each file has its stage table's header and reads back the same."""
    assert list(batch.files) == upload_names(), batch.name
    assert json.loads(batch.files[MANIFEST]) == build_manifest(batch.name, batch.files), "the manifest does not describe the files"
    for name, rows in files.items():
        lines = list(csv.reader(io.StringIO(batch.files[f"{name}.csv"].decode("utf-8"), newline="")))
        assert lines[0] == COLUMNS[name], name
        assert lines[1:] == [[r[c] for c in COLUMNS[name]] + r.get(EXTRA, []) for r in rows], name


def baseline_findings(files):
    """Data-quality findings the clean data has on purpose."""
    used = {i["alert_type_id"] for i in files["alert_incidents"]}
    never = [a["alert_type_id"] for a in files["alert_types"] if a["alert_type_id"] not in used]
    unassigned = [i["incident_id"] for i in files["alert_incidents"] if not i["resolved_at"]
                  and not i["assigned_user_id"]]
    return [
        (" ".join(never), "alert_type_id", "Not planted: alert type never fired (retired)", "DATA_QUALITY",
         f"DQ22 (INFO), {len(never)} row(s); same in the clean upload"),
        (" ".join(unassigned), "assigned_user_id", "Not planted: open incident not picked up yet", "DATA_QUALITY",
         f"DQ26 (INFO), {len(unassigned)} row(s); same in the clean upload"),
    ]


# ---------------------------------------------------------------- enrichment cases

# (case, what the file sends, device type, alert type, columns left empty, other change, expected outcome).
# The outcome is LOADED (the warehouse load fills the empty values) or the reject reason of the row.
ENRICHMENT_CASES = [
    ("E1", "store_id empty", "Door Manager", "AT01", ("store_id",), {}, "LOADED"),
    ("E2", "device_id empty", "Door Manager", "AT02", ("device_id",), {}, "LOADED"),
    ("E3", "alert_type_id empty", "Door Manager", "AT04", ("alert_type_id",), {}, "LOADED"),
    ("E4", "alert_id empty", "Door Manager", "AT05", ("alert_id",), {}, "LOADED"),
    ("E5", "store_id, device_id and alert_type_id empty; alert_id sent", "Door Manager", "AT06",
     ("store_id", "device_id", "alert_type_id"), {}, "LOADED"),
    ("E6", "store_id and alert_id empty", "Door Manager", "AT08", ("store_id", "alert_id"), {}, "LOADED"),
    ("N1", "device_id and alert_id empty: nothing to take the device from", "Door Manager", "AT09",
     ("device_id", "alert_id"), {}, "MISSING_REQUIRED"),
    ("N2", "device_id empty and alert_id malformed (ALR-D001)", "Cellular Router", "AT03",
     ("device_id",), {"alert_id": "ALR-D001"}, "BAD_PATTERN"),
    ("N3", "store_id sent but it is not the store of the device", "Camera", "AT07", (), {"store_id": "other"},
     "INCONSISTENT_VALUE"),
    ("N4", "device_id and store_id empty, alert_id names a device that does not exist (D999)", "Door Manager",
     "AT01", ("device_id", "store_id"), {"alert_id": "ALR-D999-AT01"}, "MISSING_REQUIRED"),
    ("N5", "alert_type_id and alert_id empty: nothing to take the alert type from", "Door Manager", "AT02",
     ("alert_type_id", "alert_id"), {}, "MISSING_REQUIRED"),
    ("N6", "alert_id sent that is not ALR-<device>-<alert type> of the row", "Door Manager", "AT04", (),
     {"alert_id": "ALR-D001-AT09"}, "INCONSISTENT_VALUE"),
]


def enrichment_cases(clean):
    """
    The clean files plus incidents with empty store, device, alert type or alert_id, to try the enrichment of the
    warehouse load (ops plan OI4): the load fills an empty value from the same row, and rejects what it cannot fill.
    Each incident uses a new key, so the upload can be loaded on its own or after another one. The incidents that are
    rejected get no history; the ones that are loaded get CREATED, ASSIGNED and RESOLVED.
    """
    rng = random.Random(SEED + 2)  # its own random stream: the clean and planted files do not change
    files = {name: [dict(row) for row in rows] for name, rows in clean.items()}
    stores = {s["store_id"]: s for s in files["stores"]}
    brands = {b["brand_id"]: b["brand_name"] for b in files["brands"]}
    devices = [d for d in files["device_locations"] if stores[d["store_id"]]["is_active"] == "true" and d["device_id"] != "D001"]
    streams = {i["alert_id"] for i in files["alert_incidents"]}
    assignees = [u["user_id"] for u in files["users"] if u["is_active"] == "true" and u["team_id"] in ("T01", "T02")]
    next_incident, next_event = 910701, 2001
    rows, history, cases = [], [], []

    for k, (code, sent, device_type, at_id, empty, change, outcome) in enumerate(ENRICHMENT_CASES):
        device = next(d for d in rng.sample(devices, len(devices))
                      if d["device_type"] == device_type and f"ALR-{d['device_id']}-{at_id}" not in streams)
        streams.add(f"ALR-{device['device_id']}-{at_id}")
        store_id = device["store_id"]
        if change.get("store_id") == "other":
            store_id = next(s for s, row in stores.items() if s != store_id and row["is_active"] == "true")
        created = datetime(2026, 10, 12, 8, tzinfo=timezone.utc) + timedelta(hours=5 * k)
        user = rng.choice(assignees)
        incident_id = f"INC{next_incident:06d}"
        next_incident += 1
        row = {
            "incident_id": incident_id,
            "alert_id": f"ALR-{device['device_id']}-{at_id}",
            "store_id": store_id,
            "alert_type_id": at_id,
            "brand_id": stores[store_id]["brand_id"],
            "assigned_user_id": user,
            "device_id": device["device_id"],
            "location_name": device["installed_location"],
            "next_step_action": STATUS_ACTION[RESOLVED],
            "created_at": ts(created),
            "resolved_at": ts(created + timedelta(hours=3)),
            "current_status": RESOLVED,
            "priority": AT[at_id][3],
        }
        row.update({c: v for c, v in change.items() if c != "store_id"})
        row.update({c: "" for c in empty})
        rows.append(row)
        if outcome == "LOADED":
            for offset, change_type, previous, new, by_user in (
                (0, "CREATED", "", NOT_STARTED, False),
                (20, "ASSIGNED", NOT_STARTED, IN_REVIEW, True),
                (180, "RESOLVED", IN_REVIEW, RESOLVED, False),
            ):
                history.append({"history_id": f"H{next_event:07d}", "incident_id": incident_id,
                                "event_timestamp": ts(created + timedelta(minutes=offset)), "event_type": change_type,
                                "previous_status": previous, "new_status": new,
                                "changed_by_user_id": user if by_user else "", "comments": ""})
                next_event += 1
            expected = (f"store_id={device['store_id']} device_id={device['device_id']} alert_type_id={at_id} "
                        f"alert_id=ALR-{device['device_id']}-{at_id} alert_name={AT[at_id][1]} "
                        f"brand={brands[stores[device['store_id']]['brand_id']]}")
        else:
            expected = f"rejected at the warehouse load: {outcome}"
        cases.append({"case": code, "row": row, "sent": sent, "empty": " ".join(empty) or "-", "outcome": outcome,
                      "expected": expected})

    files["alert_incidents"] += rows
    files["alert_history"] += history
    return files, cases


def render_enrichment_expected(files, cases):
    """What each enrichment incident sends, and what the warehouse load should do with it."""
    rows = [[c["case"], "alert_incidents.csv", index_of(files["alert_incidents"], c["row"]) + 2,
             c["row"]["incident_id"], c["empty"], c["sent"], c["outcome"], c["expected"]] for c in cases]
    loaded = sum(1 for c in cases if c["outcome"] == "LOADED")
    print(f"enrichment: {loaded} incidents to load after enrichment, {len(cases) - loaded} to reject")
    return render_table(["case", "file", "line_no", "record_key", "empty_columns", "what_the_file_sends", "outcome",
                         "expected_warehouse_values_or_reason"], rows)


# ---------------------------------------------------------------- build, manifest and upload

@dataclass
class Batch:
    """One upload folder, built in memory."""

    kind: str  # clean, planted or enrichment
    name: str  # the folder name, <prefix>_<stamp>
    stamp: str  # <yyyymmdd_hhmmss>, UTC
    files: dict  # file name -> bytes, in upload order: the 9 CSVs, then manifest.json
    cases: bytes | None  # the case list (planted, enrichment): never uploaded, only written locally


def upload_names():
    """The files of a folder in upload order: the CSVs, then the manifest last."""
    return [f"{name}.csv" for name in COLUMNS] + [MANIFEST]


def build_manifest(batch_name, contents):
    """What a folder holds: its batch name and stamp, and each CSV with its size and MD5 (as Cloud Storage reports it)."""
    files = [{"name": f"{name}.csv", "size": len(contents[f"{name}.csv"]),
              "md5": base64.b64encode(hashlib.md5(contents[f"{name}.csv"]).digest()).decode()} for name in COLUMNS]
    return {"batch": batch_name, "timestamp": "_".join(batch_name.split("_")[-2:]), "files": files}


def render_manifest(batch_name, contents):
    return (json.dumps(build_manifest(batch_name, contents), indent=2) + "\n").encode("utf-8")


def now_stamp():
    """The current UTC time to the second, as <yyyymmdd_hhmmss>."""
    return datetime.now(timezone.utc).strftime(STAMP_FORMAT)


def build_clean():
    """The clean source files as rows (always built: the other two kinds are made from them)."""
    rng = random.Random(SEED)
    users = build_users(rng)
    stores = build_stores()
    devices = build_devices(rng, stores)
    incidents = sorted(build_incidents(rng, stores, devices, users), key=lambda i: (i["created"], i["alert_id"]))
    clean = build_files(users, stores, devices, incidents)
    validate_clean(clean)
    return clean


def build_batch(kind, stamp=None):
    """
    Build one upload folder of this kind in memory: only that kind is derived from the clean data, and nothing is
    written to disk. `stamp` defaults to now. Raises ValueError for an unknown kind.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}, not {kind!r}")
    stamp = stamp or now_stamp()
    clean = build_clean()
    cases = None
    if kind == "clean":
        files = clean
    elif kind == "planted":
        files, errors = plant_errors(clean)
        clean_keys = {name: {r[COLUMNS[name][0]] for r in rows} for name, rows in clean.items()}
        assert all(e["row"][COLUMNS[e["table"]][0]] not in clean_keys[e["table"]] for e in errors), "planted keys are new"
        cases = render_expected(files, errors, baseline_findings(clean))
    else:
        files, enrichment = enrichment_cases(clean)
        cases = render_enrichment_expected(files, enrichment)

    assert set(files) == set(COLUMNS), sorted(files)
    name = f"{KINDS[kind]}_{stamp}"
    contents = {f"{table}.csv": render_csv(table, files[table]) for table in COLUMNS}
    contents[MANIFEST] = render_manifest(name, contents)
    batch = Batch(kind=kind, name=name, stamp=stamp, files=contents, cases=cases)
    validate_batch(batch, files)

    summary = ", ".join(f"{table} {len(files[table])}" for table in COLUMNS)
    print(f"{name}: {summary}; {sum(len(b) for b in contents.values())} bytes")
    if kind == "clean":
        open_count = sum(1 for i in clean["alert_incidents"] if not i["resolved_at"])
        print(f"clean: {len(clean['alert_incidents'])} incidents ({open_count} open), "
              f"{len(clean['alert_history'])} history events")
    return batch


def upload_batch(batch, bucket_name, client=None, dry_run=False):
    """
    Upload a batch from memory to <bucket>/<batch name>/, one object at a time, the CSVs first and manifest.json last.

    An object that already exists is never overwritten: the upload stops with PreconditionFailed. With dry_run
    nothing is uploaded. Returns the gs:// URI of each file, in upload order.
    """
    assert list(batch.files) == upload_names(), "the manifest must be the last file"
    uris = [f"gs://{bucket_name}/{batch.name}/{name}" for name in batch.files]
    if dry_run:
        return uris
    if client is None:
        from google.cloud import storage  # imported here: building files needs no GCP library or credentials

        client = storage.Client(project=os.environ.get("GCP_PROJECT_ID") or None)
    bucket = client.bucket(bucket_name)
    for (name, data), uri in zip(batch.files.items(), uris):
        bucket.blob(f"{batch.name}/{name}").upload_from_string(
            data, content_type="application/json" if name == MANIFEST else "text/csv",
            if_generation_match=0,  # only if the object does not exist yet
        )
        print(f"uploaded {uri}")
    return uris


# ---------------------------------------------------------------- local folders (command line only)

def free_stamp(out_dir, kinds):
    """Now, moved on a second while a folder of these kinds with that stamp exists in out_dir."""
    moment = datetime.now(timezone.utc).replace(microsecond=0)
    while any((out_dir / f"{KINDS[k]}_{moment.strftime(STAMP_FORMAT)}").exists() for k in kinds):
        moment += timedelta(seconds=1)
    return moment.strftime(STAMP_FORMAT)


def write_batch(batch, out_dir):
    """Write a batch's folder to out_dir, and its case list next to the folder (not in it). Returns the folder."""
    folder = Path(out_dir) / batch.name
    folder.mkdir(parents=True, exist_ok=False)
    for name, data in batch.files.items():
        (folder / name).write_bytes(data)
    if batch.cases is not None:
        (Path(out_dir) / f"{batch.name}_expected.csv").write_bytes(batch.cases)
    return folder


def generate(kinds=None, out_dir=None):
    """Build these kinds (default: all three) with one stamp and write them to out_dir (default data/). Returns {kind: folder}."""
    kinds = list(kinds or KINDS)
    out_dir = Path(out_dir) if out_dir is not None else OUT
    stamp = free_stamp(out_dir, kinds)
    return {kind: write_batch(build_batch(kind, stamp), out_dir) for kind in kinds}


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Generate the synthetic-data upload folders (clean, planted errors, enrichment), each with a manifest.json. "
        "Without --upload, write them to a local folder; with --upload, build one kind in memory and upload it.",
    )
    parser.add_argument("--kind", action="append", choices=sorted(KINDS),
                        help="a kind to write locally; repeat for several (default: all three)")
    parser.add_argument("--out", type=Path, help="local folder to write to (default: data/ next to this script)")
    parser.add_argument("--upload", choices=sorted(KINDS),
                        help="build this kind in memory and upload it to the bucket; nothing is written locally")
    parser.add_argument("--bucket", help="bucket to upload to (default: the SOURCE_BUCKET environment variable)")
    parser.add_argument("--dry-run", action="store_true", help="with --upload: list what would be uploaded, upload nothing")
    args = parser.parse_args(argv)
    if args.dry_run and not args.upload:
        parser.error("--dry-run needs --upload")
    if args.upload and (args.kind or args.out):
        parser.error("--upload writes nothing locally: drop --kind and --out")
    args.bucket = args.bucket or os.environ.get("SOURCE_BUCKET")
    if args.upload and not args.bucket:
        parser.error("--upload needs a bucket: pass --bucket or set SOURCE_BUCKET")
    return args


def main(argv=None):
    args = parse_args(argv)
    if not args.upload:
        for folder in generate(args.kind, args.out).values():
            print(f"wrote {folder}")
        return
    batch = build_batch(args.upload)
    print(f"{'Would upload' if args.dry_run else 'Uploading'} {batch.name} to gs://{args.bucket}/ "
          "(anything listening on the bucket starts on these files)")
    uris = upload_batch(batch, args.bucket, dry_run=args.dry_run)
    if args.dry_run:
        print("\n".join(uris))


if __name__ == "__main__":
    main()
