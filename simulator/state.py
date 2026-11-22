"""
The state of G2 after a batch, as stored in expected/batch_<n>.json and compared by AT-17 and AT-18.

Row counts, open/closed incidents, and one fingerprint per table: the MD5 of every row in key order, without the
columns the database fills with the wall-clock time (updated_at, beat_at, granted_at). Equal fingerprints mean equal
data, so a matching file proves the batches are repeatable.
"""

from .seed import ALL_TABLES

KEYS = {
    "brands": "brand_id", "teams": "team_id", "statuses": "status_id", "alert_types": "alert_type_id",
    "users": "user_id", "stores": "store_id", "device_locations": "device_id", "alert_incidents": "incident_id",
    "alert_history": "history_id", "store_access": "principal, crm_account_id", "heartbeat": "source",
}
WALL_CLOCK = ("updated_at", "beat_at", "granted_at")


def snapshot(conn):
    rows, fingerprints = {}, {}
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET LOCAL TimeZone = 'UTC'")  # timestamps render the same on every server
        drop = " ".join(f"- '{c}'" for c in WALL_CLOCK)
        for table in ALL_TABLES:
            cur.execute(f"SELECT count(*), coalesce(md5(string_agg((to_jsonb(x) {drop})::text, '|' "
                        f"ORDER BY {KEYS[table]})), '') FROM g2.{table} x")
            rows[table], fingerprints[table] = cur.fetchone()
        cur.execute("SELECT count(*) FILTER (WHERE resolved_at IS NULL), count(*) FILTER (WHERE resolved_at IS NOT NULL) "
                    "FROM g2.alert_incidents")
        open_count, closed_count = cur.fetchone()
    return {"rows": rows, "incidents": {"open": open_count, "closed": closed_count}, "fingerprints": fingerprints}
