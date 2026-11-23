"""
A2: one-time bootstrap of the G2 source database poc-ops-db.

1. sql/g2/schema.sql       schema g2 and its 11 tables
2. sql/g2/replication.sql  datastream_user, simulator_user, grants, publication poc_pub
3. replication slot        poc_slot, on its own: PostgreSQL refuses to create a logical slot
                           in a transaction that has already written anything
4. checks                  exits 1 if anything is missing

Cloud SQL, through the Auth Proxy (passwords from Secret Manager, never printed):
    cloud-sql-proxy gks-datalake-poc2-dev:us-central1:poc-ops-db --port 5433 &
    python scripts/g2_bootstrap.py

Local rehearsal (Docker PostgreSQL 16 with wal_level=logical, dummy app passwords):
    PG_PASSWORD=local python scripts/g2_bootstrap.py --port 5435 --local

Run once: it refuses if anything already exists. --check only runs the checks.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg import sql

REPO = Path(__file__).resolve().parents[1]
SCHEMA_SQL = REPO / "sql" / "g2" / "schema.sql"
REPLICATION_SQL = REPO / "sql" / "g2" / "replication.sql"
PROJECT = "gks-datalake-poc2-dev"
SLOT, PUBLICATION, TABLE_COUNT = "poc_slot", "poc_pub", 11


def secret(name):
    """Latest version of a Secret Manager secret, read with gcloud. Returned, never printed."""
    gcloud = shutil.which("gcloud") or "gcloud"
    run = subprocess.run([gcloud, "secrets", "versions", "access", "latest", f"--secret={name}",
                          f"--project={PROJECT}"], capture_output=True, text=True)
    if run.returncode != 0:
        sys.exit(f"Could not read secret {name}: {run.stderr.strip()}")
    return run.stdout.strip()


def leftovers(cur):
    """Anything a previous run created. The bootstrap only runs on an empty database."""
    found = []
    cur.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'g2'")
    if cur.fetchone()[0]:
        found.append("tables in schema g2")
    cur.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('datastream_user', 'simulator_user')")
    found += [f"role {name}" for (name,) in cur.fetchall()]
    cur.execute("SELECT 1 FROM pg_publication WHERE pubname = %s", (PUBLICATION,))
    if cur.fetchone():
        found.append(f"publication {PUBLICATION}")
    cur.execute("SELECT 1 FROM pg_replication_slots WHERE slot_name = %s", (SLOT,))
    if cur.fetchone():
        found.append(f"slot {SLOT}")
    return found


def create_slot(conn):
    try:
        conn.execute("SELECT pg_create_logical_replication_slot(%s, 'pgoutput')", (SLOT,))
    except psycopg.errors.InsufficientPrivilege:
        # Cloud SQL's postgres isn't a true superuser (guide 7.3): give it REPLICATION and retry.
        print("   postgres needed REPLICATION: ran ALTER ROLE ... WITH REPLICATION (record in docs/poc2/cdc.md)")
        conn.execute("ALTER ROLE CURRENT_USER WITH REPLICATION")
        conn.execute("SELECT pg_create_logical_replication_slot(%s, 'pgoutput')", (SLOT,))


def check(cur):
    """Print what exists and return the list of problems (empty = done)."""
    problems = []

    cur.execute("SHOW wal_level")
    wal = cur.fetchone()[0]
    print(f"   wal_level: {wal}")
    if wal != "logical":
        problems.append("wal_level is not logical")

    cur.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'g2'")
    tables = cur.fetchone()[0]
    print(f"   tables in g2: {tables}")
    if tables != TABLE_COUNT:
        problems.append(f"expected {TABLE_COUNT} tables in g2")

    cur.execute("SELECT count(*) FROM pg_publication_tables WHERE pubname = %s AND schemaname = 'g2'",
                (PUBLICATION,))
    published = cur.fetchone()[0]
    print(f"   tables in {PUBLICATION}: {published}")
    if published != TABLE_COUNT:
        problems.append(f"expected {TABLE_COUNT} tables in {PUBLICATION}")

    cur.execute("SELECT plugin, slot_type FROM pg_replication_slots WHERE slot_name = %s", (SLOT,))
    slot = cur.fetchone()
    print(f"   slot {SLOT}: {slot}")
    if slot != ("pgoutput", "logical"):
        problems.append(f"slot {SLOT} missing or not a pgoutput logical slot")

    cur.execute("SELECT rolname, rolreplication FROM pg_roles "
                "WHERE rolname IN ('datastream_user', 'simulator_user') ORDER BY rolname")
    roles = dict(cur.fetchall())
    print(f"   roles (name: replication): {roles}")
    if roles != {"datastream_user": True, "simulator_user": False}:
        problems.append("expected datastream_user with REPLICATION and simulator_user without")
    return problems


def main():
    parser = argparse.ArgumentParser(description="A2: bootstrap the G2 source database (run once).")
    parser.add_argument("--host", default="127.0.0.1", help="the Auth Proxy, or a local server")
    parser.add_argument("--port", type=int, default=5433)
    parser.add_argument("--db", default="g2")
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--local", action="store_true",
                        help="local rehearsal: admin password from PG_PASSWORD, dummy app passwords")
    parser.add_argument("--check", action="store_true", help="only run the checks")
    args = parser.parse_args()

    if args.local:
        admin_password = os.environ.get("PG_PASSWORD") or sys.exit("--local needs PG_PASSWORD")
    else:
        admin_password = secret("poc-ops-db-postgres")

    with psycopg.connect(host=args.host, port=args.port, dbname=args.db, user=args.user,
                         password=admin_password, connect_timeout=10, autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'cloudsqlsuperuser'")
        if args.local and cur.fetchone():
            sys.exit("--local, but this server is Cloud SQL: refusing to set dummy passwords")

        if not args.check:
            found = leftovers(cur)
            if found:
                sys.exit(f"Already bootstrapped ({', '.join(found)}). Use --check to verify.")
            ds_password, sim_password = (("local", "local") if args.local else
                                         (secret("poc-ops-db-datastream"), secret("poc-ops-db-simulator")))

            print("1/3 schema.sql")
            with conn.transaction():
                conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))

            print("2/3 replication.sql")
            text = REPLICATION_SQL.read_text(encoding="utf-8")
            for variable, value in ((":'ds_password'", ds_password), (":'sim_password'", sim_password)):
                text = text.replace(variable, sql.Literal(value).as_string(conn))  # safely quoted
            with conn.transaction():
                conn.execute(text)

            print(f"3/3 slot {SLOT}")
            create_slot(conn)

        print("checks:")
        problems = check(cur)

    if problems:
        sys.exit("FAILED: " + "; ".join(problems))
    print("OK: G2 is ready for Datastream (A4)")


if __name__ == "__main__":
    main()
