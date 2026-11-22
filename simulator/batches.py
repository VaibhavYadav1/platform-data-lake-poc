"""
`batch --n 1|2|3`: the scripted change batches of plan 0.6, used by AT-17 and AT-18.

Repeatable: each batch draws from its own fixed random seed, picks rows in key order and stamps fixed times
(gen.AS_OF plus n hours), so on a freshly seeded database every run makes the same changes. The batches must run in
order, once each, after the seed; the heartbeat rows `batch-<n>` record which ones ran.

The interpretation of the plan's wording, for review:
- "acknowledged" is the generator's ASSIGNED step: Not Started -> In Review with an assignee. A monitored incident
  moves to In Review with STATUS_CHANGED. Every status change writes a history row, as in POC 1.
- Batch 1's "20 incidents with 40 history rows" are CREATED + ASSIGNED for each new incident; the 10
  acknowledgements add 10 more history rows (50 in all).
- Batch 3's double updates are two separate transactions, so CDC sees two changes with different commit times.
"""

import random
from datetime import datetime, timedelta, timezone

from . import baseline
from .db import has_heartbeat, upsert_heartbeat
from .vendor import generate_synthetic_data as gen

NOT_STARTED, IN_REVIEW, MONITORED = gen.NOT_STARTED, gen.IN_REVIEW, gen.MONITORED
CASE_OPENED, CASE_UPDATED, REOPENED, RESOLVED = gen.CASE_OPENED, gen.CASE_UPDATED, gen.REOPENED, gen.RESOLVED
ACTION = gen.STATUS_ACTION
LAST_BASELINE_INCIDENT = "INC910550"
FUTURE_TIME = datetime(2099, 1, 1, tzinfo=timezone.utc)  # DQ34: always in the future
UNKNOWN_DEVICE = "D990"  # DQ33: fits the id format, not in device_locations
INCIDENT_COLS = ["incident_id", "alert_id", "store_id", "alert_type_id", "brand_id", "assigned_user_id", "device_id",
                 "location_name", "next_step_action", "created_at", "resolved_at", "current_status", "priority"]


class BatchError(Exception):
    pass


def iso(t):
    return gen.ts(t)


class Context:
    """What a batch needs to read and write: one cursor, its random stream, its clock and id counters."""

    def __init__(self, cur, n):
        self.cur, self.n = cur, n
        self.rng = random.Random(gen.SEED * 100 + n)
        self.t0 = gen.AS_OF + timedelta(hours=n)
        self.history_rows = 0
        cur.execute("SELECT max(incident_id), (SELECT max(history_id) FROM g2.alert_history) FROM g2.alert_incidents")
        inc, hist = cur.fetchone()
        self._next_incident, self._next_history = int(inc[3:]) + 1, int(hist[1:]) + 1

    def all(self, sql, params=()):
        self.cur.execute(sql, params)
        return self.cur.fetchall()

    def column(self, sql, params=()):
        return [r[0] for r in self.all(sql, params)]

    def assignees(self):
        return self.column("SELECT user_id FROM g2.users WHERE is_active AND team_id IN ('T01','T02','T03','T04') "
                           "ORDER BY user_id")

    def new_incident_id(self):
        self._next_incident += 1
        return f"INC{self._next_incident - 1:06d}"

    def insert_incident(self, **row):
        row = {c: row.get(c) for c in INCIDENT_COLS}
        self.cur.execute(f"INSERT INTO g2.alert_incidents ({', '.join(INCIDENT_COLS)}) "
                         f"VALUES ({', '.join(['%s'] * len(INCIDENT_COLS))})", list(row.values()))

    def history(self, incident_id, at, event_type, previous=None, new=None, user=None, comment=None):
        history_id = f"H{self._next_history:07d}"
        self._next_history += 1
        self.history_rows += 1
        self.cur.execute(
            "INSERT INTO g2.alert_history (history_id, incident_id, event_timestamp, event_type, previous_status, "
            "new_status, changed_by_user_id, comments) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (history_id, incident_id, at, event_type, previous, new, user, comment),
        )

    def set_status(self, incident_id, status, at, user=None, event_type="STATUS_CHANGED", previous=None,
                   resolved_at="keep"):
        sets, params = ["current_status = %s", "next_step_action = %s"], [status, ACTION[status]]
        if resolved_at != "keep":
            sets.append("resolved_at = %s")
            params.append(resolved_at)
        if event_type == "ASSIGNED":
            sets.append("assigned_user_id = %s")
            params.append(user)
        self.cur.execute(f"UPDATE g2.alert_incidents SET {', '.join(sets)} WHERE incident_id = %s",
                         [*params, incident_id])
        self.history(incident_id, at, event_type, previous, status, user)


def batch_1(conn, ctx):
    """Insert 20 incidents (CREATED + ASSIGNED each); acknowledge 10 open incidents."""
    devices = ctx.all("SELECT device_id, store_id, installed_location, device_type FROM g2.device_locations "
                      "WHERE device_id <> %s ORDER BY device_id", (baseline.PROBE_DEVICE_ID,))
    brand_of = dict(ctx.all("SELECT store_id, brand_id FROM g2.stores"))
    types = ctx.all("SELECT alert_type_id, device_type, default_priority FROM g2.alert_types "
                    "WHERE is_active ORDER BY alert_type_id")
    open_streams = set(ctx.column("SELECT alert_id FROM g2.alert_incidents WHERE resolved_at IS NULL"))
    assignees = ctx.assignees()
    by_type = {}
    for d in devices:
        by_type.setdefault(d[3], []).append(d)

    inserted = []
    while len(inserted) < 20:
        at_id, device_type, priority = ctx.rng.choice(types)
        device_id, store_id, location, _ = ctx.rng.choice(by_type[device_type])
        alert_id = f"ALR-{device_id}-{at_id}"
        if alert_id in open_streams:  # one open incident per alert stream, as in POC 1
            continue
        open_streams.add(alert_id)
        created = ctx.t0 + timedelta(minutes=3 * len(inserted))
        assigned_at = created + timedelta(minutes=ctx.rng.randint(5, 30))
        user = ctx.rng.choice(assignees)
        incident_id = ctx.new_incident_id()
        ctx.insert_incident(incident_id=incident_id, alert_id=alert_id, store_id=store_id, alert_type_id=at_id,
                            brand_id=brand_of[store_id], assigned_user_id=user, device_id=device_id,
                            location_name=location, next_step_action=ACTION[IN_REVIEW], created_at=created,
                            current_status=IN_REVIEW, priority=priority)
        ctx.history(incident_id, created, "CREATED", None, NOT_STARTED)
        ctx.history(incident_id, assigned_at, "ASSIGNED", NOT_STARTED, IN_REVIEW, user)
        inserted.append(incident_id)

    candidates = ctx.all("SELECT incident_id, current_status, assigned_user_id FROM g2.alert_incidents "
                         "WHERE resolved_at IS NULL AND current_status IN (%s, %s) ORDER BY incident_id",
                         (NOT_STARTED, MONITORED))
    if len(candidates) < 10:
        raise BatchError(f"batch 1 needs 10 open Not Started or monitored incidents, found {len(candidates)}")
    acknowledged = sorted(ctx.rng.sample(candidates, 10))
    for i, (incident_id, status, user) in enumerate(acknowledged):
        user = user or ctx.rng.choice(assignees)
        ctx.set_status(incident_id, IN_REVIEW, ctx.t0 + timedelta(minutes=90 + 2 * i), user,
                       "ASSIGNED" if status == NOT_STARTED else "STATUS_CHANGED", status)
    return {"inserted": inserted, "acknowledged": [a[0] for a in acknowledged]}


def batch_2(conn, ctx):
    """Close 15 incidents; delete 3 incidents and their history; move 1 device to another store."""
    open_incidents = ctx.all("SELECT incident_id, current_status FROM g2.alert_incidents "
                             "WHERE resolved_at IS NULL ORDER BY incident_id")
    closed = sorted(ctx.rng.sample(open_incidents, 15))
    for i, (incident_id, status) in enumerate(closed):
        at = ctx.t0 + timedelta(minutes=2 * i)
        ctx.set_status(incident_id, RESOLVED, at, event_type="RESOLVED", previous=status, resolved_at=at)

    deletable = ctx.column("SELECT incident_id FROM g2.alert_incidents WHERE resolved_at IS NOT NULL "
                           "AND resolved_at < %s AND incident_id <= %s ORDER BY incident_id",
                           (gen.AS_OF, LAST_BASELINE_INCIDENT))
    deleted = sorted(ctx.rng.sample(deletable, 3))
    ctx.cur.execute("DELETE FROM g2.alert_history WHERE incident_id = ANY(%s)", (deleted,))
    deleted_history = ctx.cur.rowcount
    ctx.cur.execute("DELETE FROM g2.alert_incidents WHERE incident_id = ANY(%s)", (deleted,))

    devices = ctx.all("SELECT device_id, store_id FROM g2.device_locations WHERE device_id <> %s ORDER BY device_id",
                      (baseline.PROBE_DEVICE_ID,))
    device_id, from_store = ctx.rng.choice(devices)
    stores = ctx.column("SELECT store_id FROM g2.stores WHERE is_active AND store_id NOT IN (%s, %s) "
                        "ORDER BY store_id", (baseline.PROBE_STORE_ID, from_store))
    to_store = ctx.rng.choice(stores)
    ctx.cur.execute("UPDATE g2.device_locations SET store_id = %s WHERE device_id = %s", (to_store, device_id))
    return {"closed": [c[0] for c in closed], "deleted": deleted, "deleted_history_rows": deleted_history,
            "moved_device": {"device_id": device_id, "from_store": from_store, "to_store": to_store}}


def batch_3(conn, ctx):
    """Update 5 incidents twice (two transactions); re-open 2; plant DQ34, DQ33 and DQ38."""
    assignees = ctx.assignees()
    twice = sorted(ctx.rng.sample(ctx.all(
        "SELECT incident_id, current_status, assigned_user_id FROM g2.alert_incidents WHERE resolved_at IS NULL "
        "AND current_status NOT IN (%s, %s) ORDER BY incident_id", (CASE_OPENED, CASE_UPDATED)), 5))
    users = {}
    for i, (incident_id, status, user) in enumerate(twice):
        users[incident_id] = user or ctx.rng.choice(assignees)
        ctx.set_status(incident_id, CASE_OPENED, ctx.t0 + timedelta(minutes=2 * i), users[incident_id],
                       previous=status)

    reopened = sorted(ctx.rng.sample(ctx.column(
        "SELECT incident_id FROM g2.alert_incidents WHERE resolved_at IS NOT NULL AND resolved_at < %s "
        "AND incident_id <= %s ORDER BY incident_id", (gen.AS_OF, LAST_BASELINE_INCIDENT)), 2))
    for i, incident_id in enumerate(reopened):
        ctx.set_status(incident_id, REOPENED, ctx.t0 + timedelta(minutes=20 + 2 * i), event_type="REOPENED",
                       previous=RESOLVED, resolved_at=None)

    if ctx.column("SELECT 1 FROM g2.device_locations WHERE device_id = %s", (UNKNOWN_DEVICE,)):
        raise BatchError(f"{UNKNOWN_DEVICE} exists, so it can't be the planted unknown device")
    devices = ctx.all("SELECT d.device_id, d.store_id, d.installed_location, s.brand_id FROM g2.device_locations d "
                      "JOIN g2.stores s USING (store_id) WHERE d.device_type = 'Door Manager' AND d.device_id <> %s "
                      "ORDER BY d.device_id", (baseline.PROBE_DEVICE_ID,))
    not_started_action = dict(ctx.all("SELECT alert_type_id, not_started_next_step_action FROM g2.alert_types"))
    planted = {}
    for dq, minute in (("DQ34", 30), ("DQ33", 35), ("DQ38", 40)):
        device_id, store_id, location, brand_id = ctx.rng.choice(devices)
        if dq == "DQ33":
            device_id = UNKNOWN_DEVICE
        created = FUTURE_TIME if dq == "DQ34" else ctx.t0 + timedelta(minutes=minute)
        resolved = created - timedelta(hours=1) if dq == "DQ38" else None
        incident_id = ctx.new_incident_id()
        ctx.insert_incident(incident_id=incident_id, alert_id=f"ALR-{device_id}-AT01", store_id=store_id,
                            alert_type_id="AT01", brand_id=brand_id, device_id=device_id, location_name=location,
                            next_step_action=ACTION[RESOLVED] if resolved else not_started_action["AT01"],
                            created_at=created, resolved_at=resolved,
                            current_status=RESOLVED if resolved else NOT_STARTED, priority="P1")
        ctx.history(incident_id, created, "CREATED", None, NOT_STARTED)
        if resolved:
            ctx.history(incident_id, resolved, "RESOLVED", NOT_STARTED, RESOLVED)
        planted[dq] = incident_id

    # The second change of each incident in its own transaction, after the first one commits.
    conn.commit()
    for i, (incident_id, _, _) in enumerate(twice):
        ctx.set_status(incident_id, CASE_UPDATED, ctx.t0 + timedelta(minutes=60 + 2 * i), users[incident_id],
                       previous=CASE_OPENED)
    return {"changed_twice": [t[0] for t in twice], "reopened": reopened, "planted": planted}


BATCHES = {1: batch_1, 2: batch_2, 3: batch_3}


def run_batch(conn, n, log=print):
    with conn.cursor() as cur:
        if not has_heartbeat(cur, baseline.HEARTBEAT_SOURCE):
            raise BatchError("G2 isn't seeded: run `seed` first")
        if has_heartbeat(cur, f"batch-{n}"):
            raise BatchError(f"batch {n} already ran; locally, start again with `seed --reset`")
        if n > 1 and not has_heartbeat(cur, f"batch-{n - 1}"):
            raise BatchError(f"run batch {n - 1} first: the batches build on each other")
        conn.rollback()
        try:
            ctx = Context(cur, n)
            changes = BATCHES[n](conn, ctx)
            upsert_heartbeat(cur, f"batch-{n}")  # last, so it only says "done" when the batch is complete
            conn.commit()
        except Exception:
            conn.rollback()
            if n == 3:
                log("batch 3 failed; if its first transaction committed, re-seed locally with `seed --reset`")
            raise
    changes["history_rows_inserted"] = ctx.history_rows
    return changes
