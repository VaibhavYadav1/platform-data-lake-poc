"""
`tick`: one continuous-mode tick (task A8, guide 10.5). Cloud Scheduler starts one every 5 minutes.

Each tick is its own Cloud Run execution with no memory of the last, so "about every 10 ticks" is a 1-in-10 draw.
Steps, in order:
1. G2 changes, one transaction: open 3-6 incidents, update 3-6, close 2-5 (a history row for each), delete one
   resolved incident about 1 tick in 10, move a device about 1 tick in 50. About 0.5% of new incidents are planted
   defects: an unknown device (DQ33) or a time in the future (DQ34).
2. Case events (A7), only when CASE_TOPIC is set.
3. Wheel events (A9), only when G2DL_PROJECT is set. A9 isn't built yet, so setting it fails the tick.
4. CRM export (B2), only when CRM_BUCKET is set, on the first tick after each full hour.
5. The heartbeat, last and in its own transaction, so a failed step above leaves it stale and the watchdog sees it.

RATE scales the counts (1.0 = as above, 0 = heartbeat and one case event only).

This module imports neither the vendored generator nor `seed`/`batches`: those need `data-lake-schema` from the
Phase 1 registry, and the cloud image installs only `requirements-runtime.txt`. Status actions come from
`g2.statuses` instead. The probe store S999 and device D999 are never touched (AT-16 and AT-22 use them).
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import baseline
from .db import upsert_heartbeat

NOT_STARTED = "Not Started"
IN_REVIEW = "In Review"
MONITORED = "Alert is being monitored"
CASE_OPENED = "Case Opened"
REOPENED = "Re-Opened"
RESOLVED = "Resolved"
CASE_UPDATED = "Case Updated"

# How an open incident moves on, as in POC 1's generator: (new status, history event type)
NEXT_STEPS = {
    NOT_STARTED: [(IN_REVIEW, "ASSIGNED")],
    IN_REVIEW: [(CASE_OPENED, "STATUS_CHANGED"), (MONITORED, "STATUS_CHANGED")],
    MONITORED: [(CASE_OPENED, "STATUS_CHANGED")],
    CASE_OPENED: [(CASE_UPDATED, "STATUS_CHANGED")],
    CASE_UPDATED: [(CASE_UPDATED, "STATUS_CHANGED")],
    REOPENED: [(CASE_OPENED, "STATUS_CHANGED")],
}

UNKNOWN_DEVICE = "D990"  # DQ33: fits the id format, not in device_locations (same as batch 3)
FUTURE_TIME = datetime(2099, 1, 1, tzinfo=timezone.utc)  # DQ34
P_DELETE, P_MOVE, P_PLANT = 0.10, 0.02, 0.005
INCIDENT_COLS = ["incident_id", "alert_id", "store_id", "alert_type_id", "brand_id", "assigned_user_id", "device_id",
                 "location_name", "next_step_action", "created_at", "resolved_at", "current_status", "priority"]


class TickError(Exception):
    pass


def scaled(rng, lo, hi, rate):
    return max(0, round(rng.randint(lo, hi) * rate))


@dataclass
class TickResult:
    rate: float
    opened: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    closed: list = field(default_factory=list)
    deleted: list = field(default_factory=list)
    moved_device: dict | None = None
    planted: dict = field(default_factory=dict)
    history_rows: int = 0
    case_events: int | str = "off"
    wheel_events: int | str = "off"
    crm_export: str = "no"

    def summary(self):
        return (f"tick rate={self.rate} opened={len(self.opened)} updated={len(self.updated)} "
                f"closed={len(self.closed)} deleted={len(self.deleted)} moved={1 if self.moved_device else 0} "
                f"planted={len(self.planted)} history={self.history_rows} case_events={self.case_events} "
                f"wheel_events={self.wheel_events} crm={self.crm_export} heartbeat=ok")


class G2Changes:
    """The G2 part of a tick, on one cursor inside one transaction."""

    def __init__(self, cur, rng, now, result):
        self.cur, self.rng, self.now, self.result = cur, rng, now, result
        self.touched = set()
        self._at = 0
        cur.execute("SELECT max(incident_id), (SELECT max(history_id) FROM g2.alert_history) FROM g2.alert_incidents")
        inc, hist = cur.fetchone()
        if inc is None or hist is None:
            raise TickError("G2 has no incidents or history: is it seeded?")
        self._next_incident, self._next_history = int(inc[3:]) + 1, int(hist[1:]) + 1
        self.action = dict(self.all("SELECT status_name, next_step_action FROM g2.statuses"))
        missing = {s for s in NEXT_STEPS if s not in self.action} | ({RESOLVED} - set(self.action))
        if missing:
            raise TickError(f"g2.statuses has no {sorted(missing)}: is it seeded?")
        self.assignees = [r[0] for r in self.all(
            "SELECT user_id FROM g2.users WHERE is_active AND team_id IN ('T01','T02','T03','T04') ORDER BY user_id")]

    def all(self, sql, params=()):
        self.cur.execute(sql, params)
        return self.cur.fetchall()

    def at(self):
        """A distinct, increasing time per change, so the history reads in order."""
        self._at += 1
        return self.now + timedelta(milliseconds=self._at)

    def history(self, incident_id, at, event_type, previous, new, user=None):
        history_id = f"H{self._next_history:07d}"
        self._next_history += 1
        self.result.history_rows += 1
        self.cur.execute(
            "INSERT INTO g2.alert_history (history_id, incident_id, event_timestamp, event_type, previous_status, "
            "new_status, changed_by_user_id, comments) VALUES (%s, %s, %s, %s, %s, %s, %s, NULL)",
            (history_id, incident_id, at, event_type, previous, new, user),
        )

    def open_incidents(self, n):
        if n == 0:
            return
        devices = self.all(
            "SELECT d.device_id, d.store_id, d.installed_location, d.device_type, s.brand_id "
            "FROM g2.device_locations d JOIN g2.stores s USING (store_id) "
            "WHERE s.is_active AND d.device_id <> %s AND d.store_id <> %s ORDER BY d.device_id",
            (baseline.PROBE_DEVICE_ID, baseline.PROBE_STORE_ID))
        types = self.all("SELECT alert_type_id, device_type, default_priority, not_started_next_step_action "
                         "FROM g2.alert_types WHERE is_active ORDER BY alert_type_id")
        open_streams = {r[0] for r in self.all("SELECT alert_id FROM g2.alert_incidents WHERE resolved_at IS NULL")}
        by_type = {}
        for d in devices:
            by_type.setdefault(d[3], []).append(d)
        types = [t for t in types if t[1] in by_type]
        if not types:
            raise TickError("no active alert type has a device in an active store")

        for _ in range(n * 20):  # one open incident per alert stream; give up rather than loop forever
            if len(self.result.opened) == n:
                break
            at_id, device_type, priority, not_started_action = self.rng.choice(types)
            device_id, store_id, location, _, brand_id = self.rng.choice(by_type[device_type])
            created, planted = self.at(), None
            if self.rng.random() < P_PLANT:
                planted = self.rng.choice(["DQ33", "DQ34"])
                if planted == "DQ33":
                    device_id = UNKNOWN_DEVICE
                else:
                    created = FUTURE_TIME
            alert_id = f"ALR-{device_id}-{at_id}"
            if alert_id in open_streams:
                continue
            open_streams.add(alert_id)
            incident_id = f"INC{self._next_incident:06d}"
            self._next_incident += 1
            row = dict(incident_id=incident_id, alert_id=alert_id, store_id=store_id, alert_type_id=at_id,
                       brand_id=brand_id, device_id=device_id, location_name=location,
                       next_step_action=not_started_action, created_at=created, current_status=NOT_STARTED,
                       priority=priority)
            self.cur.execute(f"INSERT INTO g2.alert_incidents ({', '.join(INCIDENT_COLS)}) "
                             f"VALUES ({', '.join(['%s'] * len(INCIDENT_COLS))})",
                             [row.get(c) for c in INCIDENT_COLS])
            self.history(incident_id, created, "CREATED", None, NOT_STARTED)
            self.result.opened.append(incident_id)
            self.touched.add(incident_id)
            if planted:
                self.result.planted[incident_id] = planted

    def open_pool(self, statuses):
        """Open incidents this tick may change: not the probe's, not planted future ones, not touched yet."""
        rows = self.all(
            "SELECT incident_id, current_status, assigned_user_id FROM g2.alert_incidents "
            "WHERE resolved_at IS NULL AND current_status = ANY(%s) AND created_at <= %s "
            "AND device_id IS DISTINCT FROM %s AND store_id IS DISTINCT FROM %s ORDER BY incident_id",
            (list(statuses), self.now, baseline.PROBE_DEVICE_ID, baseline.PROBE_STORE_ID))
        return [r for r in rows if r[0] not in self.touched]

    def set_status(self, incident_id, previous, status, event_type, user=None, resolved_at="keep"):
        at = self.at()
        sets, params = ["current_status = %s", "next_step_action = %s"], [status, self.action[status]]
        if resolved_at != "keep":
            sets.append("resolved_at = %s")
            params.append(at if resolved_at == "now" else resolved_at)
        if event_type == "ASSIGNED":
            sets.append("assigned_user_id = %s")
            params.append(user)
        self.cur.execute(f"UPDATE g2.alert_incidents SET {', '.join(sets)} WHERE incident_id = %s",
                         [*params, incident_id])
        self.history(incident_id, at, event_type, previous, status, user)
        self.touched.add(incident_id)

    def update_incidents(self, n):
        pool = self.open_pool(NEXT_STEPS)
        for incident_id, status, user in self.rng.sample(pool, min(n, len(pool))):
            new_status, event_type = self.rng.choice(NEXT_STEPS[status])
            user = user or (self.rng.choice(self.assignees) if self.assignees else None)
            self.set_status(incident_id, status, new_status, event_type, user)
            self.result.updated.append(incident_id)

    def close_incidents(self, n):
        pool = self.open_pool(NEXT_STEPS)
        for incident_id, status, _ in self.rng.sample(pool, min(n, len(pool))):
            self.set_status(incident_id, status, RESOLVED, "RESOLVED", resolved_at="now")
            self.result.closed.append(incident_id)

    def maybe_delete(self):
        if self.rng.random() >= P_DELETE:
            return
        candidates = [r[0] for r in self.all(
            "SELECT incident_id FROM g2.alert_incidents WHERE resolved_at IS NOT NULL "
            "AND device_id IS DISTINCT FROM %s AND store_id IS DISTINCT FROM %s ORDER BY incident_id",
            (baseline.PROBE_DEVICE_ID, baseline.PROBE_STORE_ID)) if r[0] not in self.touched]
        if not candidates:
            return
        incident_id = self.rng.choice(candidates)
        self.cur.execute("DELETE FROM g2.alert_history WHERE incident_id = %s", (incident_id,))
        self.cur.execute("DELETE FROM g2.alert_incidents WHERE incident_id = %s", (incident_id,))
        self.result.deleted.append(incident_id)

    def maybe_move_device(self):
        if self.rng.random() >= P_MOVE:
            return
        devices = self.all("SELECT device_id, store_id FROM g2.device_locations "
                           "WHERE device_id <> %s AND store_id <> %s ORDER BY device_id",
                           (baseline.PROBE_DEVICE_ID, baseline.PROBE_STORE_ID))
        if not devices:
            return
        device_id, from_store = self.rng.choice(devices)
        stores = [r[0] for r in self.all("SELECT store_id FROM g2.stores WHERE is_active AND store_id NOT IN (%s, %s) "
                                         "ORDER BY store_id", (baseline.PROBE_STORE_ID, from_store))]
        if not stores:
            return
        to_store = self.rng.choice(stores)
        self.cur.execute("UPDATE g2.device_locations SET store_id = %s WHERE device_id = %s", (to_store, device_id))
        self.result.moved_device = {"device_id": device_id, "from_store": from_store, "to_store": to_store}


def publish_case_events(topic, n, rng):
    try:
        from .case_events import publish_case_events as publish  # task A7
    except ImportError as e:
        raise TickError("CASE_TOPIC is set, but this image has no case-event publisher yet (task A7)") from e
    return publish(topic, n, rng)


def write_crm_export(bucket, prefix, now):
    from .crm_export import CRMState, generate_export, upload_to_gcs

    export_time = now.replace(minute=0, second=0, microsecond=0)
    state = CRMState.initialize(n_accounts=50, n_stores=100, seed=42)
    files = generate_export(state=state, export_time=export_time, change_rate=0.1)
    return upload_to_gcs(bucket, prefix, export_time, files)


def run_tick(conn, rate=1.0, case_topic=None, g2dl_project=None, crm_bucket=None, crm_prefix="crm",
             rng=None, now=None):
    """One tick on one connection. Raises on any failure; the heartbeat is then not updated."""
    if rate < 0:
        raise TickError(f"RATE must be 0 or more, not {rate}")
    rng = rng or random.Random()
    now = now or datetime.now(timezone.utc)
    result = TickResult(rate=rate)

    # 1. G2, one transaction
    try:
        with conn.cursor() as cur:
            g2 = G2Changes(cur, rng, now, result)
            g2.open_incidents(scaled(rng, 3, 6, rate))
            g2.update_incidents(scaled(rng, 3, 6, rate))
            g2.close_incidents(scaled(rng, 2, 5, rate))
            g2.maybe_delete()
            g2.maybe_move_device()
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # 2. Case events (A7): 1-5, never 0
    if case_topic:
        result.case_events = publish_case_events(case_topic, max(1, scaled(rng, 1, 5, rate)), rng)

    # 3. Wheel events (A9)
    if g2dl_project:
        raise TickError("G2DL_PROJECT is set, but wheel events (task A9) aren't built yet")

    # 4. CRM (B2): the first tick after each full hour (ticks are 5 minutes apart)
    if crm_bucket and now.minute < 5:
        result.crm_export = write_crm_export(crm_bucket, crm_prefix, now)

    # 5. Heartbeat, last
    with conn.cursor() as cur:
        upsert_heartbeat(cur, baseline.HEARTBEAT_SOURCE)
    conn.commit()
    return result
