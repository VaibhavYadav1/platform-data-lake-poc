"""One connection per command. db-f1-micro allows few connections, so never pool (A8 pitfall)."""

import psycopg

from .config import Settings

SCHEMA = "g2"


def connect(settings: Settings) -> psycopg.Connection:
    if settings.instance:
        # Cloud SQL through the Python connector and a Secret Manager password comes with A3/A8.
        raise NotImplementedError("PG_INSTANCE is not supported yet: connect with PG_HOST (locally, or through the Auth Proxy)")
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
