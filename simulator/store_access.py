"""
`grant`, `revoke` and `store-access-seed`: who may see which CRM account (g2.store_access; tasks D3, D6, AT-25).

dbt turns these rows into sec_<env>.map_tenant_access (principal -> top-level customer account), which the tenant
row policy reads. The seed adds the POC D test rows once, after `seed`; `seed` itself stays once-only and leaves
store_access empty. `revoke` and `grant` are the two halves of the access-removal test (D6).

Test accounts come from the CRM export generator (crm_export.py, seed 42): ACC00001 is a top-level customer with
children ACC00002..ACC00004, ACC00005 is another top-level customer, ACC00031 is a vendor.
"""

import re
from dataclasses import dataclass

from .db import SCHEMA

# Same rule as the CHECK on g2.store_access.principal in sql/g2/schema.sql.
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DEFAULT_PROJECT = "gks-datalake-poc2-dev"


class StoreAccessError(Exception):
    pass


@dataclass(frozen=True)
class AccessRow:
    name: str      # service account id; the email is <name>@<project>.iam.gserviceaccount.com
    account: str   # CRM account id
    reason: str    # what the row proves in map_tenant_access


# POC D test rows (security design section 6.1). The last two must not add a tenant: one folds into tenant A,
# the other is dropped because a vendor is never a tenant.
TEST_ROWS = (
    AccessRow("sa-tenant-a-user", "ACC00001", "tenant A user -> tenant ACC00001"),
    AccessRow("sa-app-tenant-a", "ACC00001", "tenant A app identity -> tenant ACC00001"),
    AccessRow("sa-tenant-b-user", "ACC00005", "tenant B user -> tenant ACC00005"),
    AccessRow("sa-app-tenant-b", "ACC00005", "tenant B app identity -> tenant ACC00005"),
    AccessRow("sa-tenant-a-user", "ACC00002", "child of ACC00001: must fold into tenant ACC00001, no new tenant"),
    AccessRow("sa-tenant-b-user", "ACC00031", "vendor account: must be dropped, tenant B gains nothing"),
)


def service_account_email(name, project=DEFAULT_PROJECT):
    return f"{name}@{project}.iam.gserviceaccount.com"


def check_principal(principal):
    if not EMAIL.match(principal or ""):
        raise StoreAccessError(f"principal must be an email (what SESSION_USER() returns), not {principal!r}")


def check_account(account):
    if not account or account != account.strip():
        raise StoreAccessError(f"account must be a CRM account id, not {account!r}")


def grant(cur, principal, account):
    """Add one grant. Returns True if a row was added, False if it already existed (idempotent)."""
    check_principal(principal)
    check_account(account)
    cur.execute(
        f"INSERT INTO {SCHEMA}.store_access (principal, crm_account_id) VALUES (%s, %s) "
        "ON CONFLICT (principal, crm_account_id) DO NOTHING",
        (principal, account),
    )
    return cur.rowcount == 1


def revoke(cur, principal, account):
    """Remove one grant. Returns True if a row was removed, False if there was none."""
    check_principal(principal)
    check_account(account)
    cur.execute(
        f"DELETE FROM {SCHEMA}.store_access WHERE principal = %s AND crm_account_id = %s",
        (principal, account),
    )
    return cur.rowcount == 1


def seed_rows(project=DEFAULT_PROJECT):
    """The test rows as (principal, account, reason)."""
    return [(service_account_email(r.name, project), r.account, r.reason) for r in TEST_ROWS]


def seed_store_access(conn, project=DEFAULT_PROJECT, dry_run=False, log=print):
    """Grant every test row in one transaction. Re-running adds nothing. Returns the number of rows added."""
    rows = seed_rows(project)
    for principal, _account, _reason in rows:
        check_principal(principal)
    if dry_run:
        for principal, account, reason in rows:
            log(f"  would grant {principal} -> {account}   ({reason})")
        return 0
    added = 0
    with conn.transaction(), conn.cursor() as cur:
        for principal, account, reason in rows:
            new = grant(cur, principal, account)
            added += new
            log(f"  {'granted' if new else 'exists '} {principal} -> {account}   ({reason})")
    log(f"store_access: {added} row(s) added, {len(rows) - added} already present")
    return added


def run(conn, command, principal=None, account=None, project=DEFAULT_PROJECT, dry_run=False, log=print):
    """Entry point for the cli subcommands. Returns the exit code."""
    try:
        if command == "store-access-seed":
            seed_store_access(conn, project, dry_run=dry_run, log=log)
            return 0
        with conn.transaction(), conn.cursor() as cur:
            if command == "grant":
                changed = grant(cur, principal, account)
                log(f"{'granted' if changed else 'already granted'}: {principal} -> {account}")
            elif command == "revoke":
                changed = revoke(cur, principal, account)
                log(f"{'revoked' if changed else 'nothing to revoke'}: {principal} -> {account}")
            else:
                raise StoreAccessError(f"unknown command {command!r}")
        return 0
    except StoreAccessError as e:
        log(f"error: {e}")
        return 1
