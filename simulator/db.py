"""One connection per command. db-f1-micro allows few connections, so never pool (A8 pitfall)."""

import psycopg

from .config import Settings

SCHEMA = "g2"


def connect(settings: Settings) -> psycopg.Connection:
    if settings.instance:
        # A8 doesn't need the Python connector: the Cloud Run job mounts Cloud SQL's Unix socket and sets
        # PG_HOST=/cloudsql/<connection name>, with PG_PASSWORD injected from Secret Manager (guide 10.6, as built).
        raise NotImplementedError("PG_INSTANCE is not supported: set PG_HOST (localhost, the Auth Proxy, "
                                  "or /cloudsql/<connection name> in Cloud Run)")
    if not settings.host:
        raise SystemExit("Set PG_HOST (for example localhost) and PG_DB, PG_USER, PG_PASSWORD as needed")
    return psycopg.connect(host=settings.host, port=settings.port, dbname=settings.db, user=settings.user,
                           password=settings.password, connect_timeout=10)


def upsert_heartbeat(cur, source):
    cur.execute(
        "INSERT INTO g2.heartbeat (source, beat_at) VALUES (%s, now()) "
        "ON CONFLICT (source) DO UPDATE SET beat_at = now()",
        (source,),
    )


def has_heartbeat(cur, source):
    cur.execute("SELECT 1 FROM g2.heartbeat WHERE source = %s", (source,))
    return cur.fetchone() is not None
