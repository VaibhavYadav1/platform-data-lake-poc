"""The D5 security cases as plain functions: runner in, list of Result out.

test_access.py only loops over identities and asserts; keeping the logic here lets the offline tests check it
with a fake runner.
"""
from __future__ import annotations

import time

from security_lib import (
    EMAIL, PII_PROBE, TENANT_READERS, TEST_APP, Config, Outcome, PublishedTable, Result, attempt, run,
)

CANARY = "zz_security_canary"


def _actual(o: Outcome) -> str:
    return o.kind if o.kind != "denied" else f"denied ({o.reason})"


# ------------------------------------------------------------------------------ case 1 and 6
def mapped_tenants(runner, cfg: Config, identity: str) -> list[str]:
    rows = runner.query(
        f"SELECT DISTINCT tenant_id FROM {cfg.table('sec', 'map_tenant_access')} WHERE principal_hash = TO_HEX(SHA256(LOWER(@p)))",
        params={"p": ("STRING", identity)},
    )
    return sorted(r["tenant_id"] for r in rows)


def case1_isolation(runner, cfg: Config, identity: str, tables: list[PublishedTable]) -> list[Result]:
    """Each tenant identity sees exactly the internal count for its tenants, and no other tenant's rows."""
    mine = mapped_tenants(runner, cfg, identity)
    if not mine:
        return [Result(1, "isolation", identity, "sec.map_tenant_access", ">= 1 tenant", "no mapping", False,
                       detail="no map_tenant_access row: seed store_access (D3) and publish first")]
    out = []
    for t in tables:
        fq = cfg.table("wh", t.name)
        internal = run(runner, f"SELECT COUNT(*) AS n FROM {fq}{t.where()}{t.and_()} tenant_id IN UNNEST(@m)",
                       params={"m": ("STRING", mine)})
        seen = run(runner, f"SELECT COUNT(*) AS n, COUNTIF(tenant_id IS NULL OR tenant_id NOT IN UNNEST(@m)) AS other "
                           f"FROM {fq}{t.where()}", identity=identity, params={"m": ("STRING", mine)})
        if internal.kind != "ok" or seen.kind != "ok":
            bad = internal if internal.kind != "ok" else seen
            out.append(Result(1, "isolation", identity, t.name, "counts", _actual(bad), False, bad.job_id, bad.message))
            continue
        n_int, n, other = internal.rows[0]["n"], seen.rows[0]["n"], seen.rows[0]["other"]
        out.append(Result(1, "isolation", identity, t.name, f"total={n_int} other=0", f"total={n} other={other}",
                          n == n_int and other == 0, seen.job_id, f"tenants={mine}"))
    # "Own rows = internal count" holds trivially when the tenant has no rows anywhere: that proves nothing.
    measured = [r for r in out if r.passed]
    if measured and len(measured) == len(out) and all(r.actual.startswith("total=0 ") for r in out):
        out.append(Result(1, "isolation", identity, "all tables", ">= 1 own row somewhere", "0 rows in every table",
                          False, detail="no data for this tenant: publish data for it before trusting case 1"))
    return out


def case6_hidden_rows(runner, cfg: Config, identity: str, tables: list[PublishedTable], columns: dict) -> list[Result]:
    """NULL-tenant stores, vendor stores and the probe store must be invisible to every tenant."""
    out = []
    for t in tables:
        cond = ["tenant_id IS NULL", "tenant_id = @vendor"]
        if "store_id" in columns.get(t.name, ()):
            cond.append("store_id = @probe")
        o = run(runner, f"SELECT COUNT(*) AS n FROM {cfg.table('wh', t.name)}{t.where()}{t.and_()} ({' OR '.join(cond)})",
                identity=identity, params={"vendor": ("STRING", cfg.vendor_account), "probe": ("STRING", cfg.probe_store)})
        n = o.rows[0]["n"] if o.kind == "ok" else None
        out.append(Result(6, "hidden_rows", identity, t.name, "0", str(n) if o.kind == "ok" else _actual(o),
                          o.kind == "ok" and n == 0, o.job_id, o.message))
    return out


def wh_columns(runner, cfg: Config) -> dict:
    rows = runner.query(f"SELECT table_name, column_name FROM `{cfg.project}.{cfg.ds('wh')}`.INFORMATION_SCHEMA.COLUMNS")
    cols: dict = {}
    for r in rows:
        cols.setdefault(r["table_name"], set()).add(r["column_name"])
    return cols


# ------------------------------------------------------------------------------ case 2
def ensure_canary(runner, cfg: Config) -> str:
    """Write attempts target an empty canary table, so a wrongly granted write can't damage published data."""
    fq = cfg.table("wh", CANARY)
    runner.query(f"CREATE TABLE IF NOT EXISTS {fq} (id INT64, tenant_id STRING)")
    return fq


def write_statements(cfg: Config, canary: str) -> dict:
    new = cfg.table("wh", f"{CANARY}_new")
    return {
        "INSERT": f"INSERT INTO {canary} (id, tenant_id) VALUES (1, 'x')",
        "UPDATE": f"UPDATE {canary} SET id = 2 WHERE TRUE",
        "DELETE": f"DELETE FROM {canary} WHERE TRUE",
        "MERGE": f"MERGE {canary} T USING (SELECT 1 AS id, 'x' AS tenant_id) S ON T.id = S.id "
                 "WHEN NOT MATCHED THEN INSERT (id, tenant_id) VALUES (S.id, S.tenant_id)",
        "CREATE TABLE": f"CREATE TABLE {new} (id INT64)",
        "ALTER TABLE": f"ALTER TABLE {canary} ADD COLUMN IF NOT EXISTS probe STRING",
        "DROP TABLE": f"DROP TABLE {canary}",
    }


def case2_read_only(runner, cfg: Config, identity: str, canary: str) -> list[Result]:
    out = []
    for verb, sql in write_statements(cfg, canary).items():
        o = run(runner, sql, identity=identity)
        out.append(Result(2, "read_only", identity, f"wh {verb}", "denied", _actual(o), o.kind == "denied",
                          o.job_id, o.message))
    return out


# ------------------------------------------------------------------------------ case 3
def upstream_targets(cfg: Config) -> dict:
    """One real table per dataset readers must not read. A missing table fails the case: it proves nothing."""
    t = {
        "raw_g2": f"`{cfg.project}.raw_g2.g2_users`",
        "raw_crm": f"`{cfg.project}.raw_crm.account_landing`",
        "raw_lpos": f"`{cfg.project}.raw_lpos.case_event`",
        "keys": f"`{cfg.project}.keys.token_key`",
        "stg": cfg.table("stg", "stg_g2__alert_incidents"),
        "prep": cfg.table("prep", "int_alert__validated"),
        "build": cfg.table("build", "dim_store"),
        "dq": cfg.table("dq", "quarantine_alert"),
        "ops": cfg.table("ops", "dq_result"),
    }
    if not cfg.sec_readable:
        t["sec"] = cfg.table("sec", "map_tenant_access")
    return t


def case3_no_upstream(runner, cfg: Config, identity: str) -> list[Result]:
    out = []
    for name, fq in upstream_targets(cfg).items():
        o = run(runner, f"SELECT COUNT(*) AS n FROM {fq}", identity=identity)
        out.append(Result(3, "no_upstream", identity, name, "denied", _actual(o), o.kind == "denied", o.job_id,
                          o.message))
    return out


# ------------------------------------------------------------------------------ case 4
def case4_no_writer(runner, cfg: Config, identity: str) -> Result:
    o = attempt(lambda: runner.impersonate(identity, cfg.writer))
    return Result(4, "no_writer_impersonation", identity, cfg.writer, "denied", _actual(o), o.kind == "denied",
                  None, o.message)


def case4_test_app_control(runner, cfg: Config) -> list[Result]:
    """Positive control: sa-test-app may impersonate the two app identities, and nothing else."""
    out = []
    for name in ("sa-app-tenant-a", "sa-app-tenant-b"):
        o = attempt(lambda n=name: runner.impersonate(cfg.sa(TEST_APP), cfg.sa(n)))
        out.append(Result(4, "test_app_allowed", cfg.sa(TEST_APP), cfg.sa(name), "ok", _actual(o), o.kind == "ok",
                          None, o.message))
    return out


# ------------------------------------------------------------------------------ case 5
def case5_pii(runner, cfg: Config) -> Result:
    """sa-pii-probe can read raw_crm but holds no tag: the contact email must come back masked, or be denied."""
    who = cfg.sa(PII_PROBE)
    # First prove the probe can read the table at all (an untagged column). Without this, a probe that lacks
    # dataset access would be "denied" too, and the case would pass without testing the tag (design issue #1).
    pre = run(runner, f"SELECT account_id FROM `{cfg.project}.raw_crm.account_landing` LIMIT 1", identity=who)
    if pre.kind != "ok":
        return Result(5, "pii_masked_or_denied", who, "raw_crm.account_landing.account_id",
                      "probe reads untagged columns", _actual(pre), False, pre.job_id,
                      "sa-pii-probe cannot read raw_crm itself: grant it viewer (terraform crm_landing_dataset)")
    o = run(runner, f"SELECT primary_contact_email AS v FROM `{cfg.project}.raw_crm.account_landing` "
                    "WHERE primary_contact_email IS NOT NULL LIMIT 20", identity=who)
    if o.kind == "denied":
        return Result(5, "pii_masked_or_denied", who, "raw_crm.account_landing.primary_contact_email",
                      "masked or denied", _actual(o), True, o.job_id, o.message)
    leaked = [r["v"] for r in o.rows if r.get("v") is not None and EMAIL.search(str(r["v"]))]
    ok = o.kind == "ok" and bool(o.rows) and not leaked
    actual = "no rows to judge" if o.kind == "ok" and not o.rows else (f"{len(leaked)} real emails" if leaked else
                                                                       "masked" if o.kind == "ok" else _actual(o))
    return Result(5, "pii_masked_or_denied", who, "raw_crm.account_landing.primary_contact_email",
                  "masked or denied", actual, ok, o.job_id, o.message)


# ------------------------------------------------------------------------------ case 7
def consistency_sql(cfg: Config, fact: PublishedTable, dim: PublishedTable) -> str:
    """One query reads both tables, so each sample is one consistent snapshot."""
    return (f"SELECT (SELECT COUNT(*) FROM {cfg.table('wh', fact.name)}{fact.where()}) AS fact_n, "
            f"(SELECT COUNT(*) FROM {cfg.table('wh', dim.name)}{dim.where()}) AS dim_n")


def judge_samples(before: tuple, after: tuple, samples: list[tuple]) -> tuple[bool, str]:
    """Pass when every sample is the old or the new version, and the old never comes back after the new."""
    seen_new = False
    for s in samples:
        if s == after:
            seen_new = True
        elif s == before:
            if seen_new and before != after:
                return False, f"old version {before} seen after the new one"
        else:
            return False, f"mixed sample {s}: neither old {before} nor new {after}"
    return True, f"{len(samples)} samples, before={before} after={after}"


def case7_publish_consistency(runner, cfg: Config, identity: str, fact: PublishedTable, dim: PublishedTable,
                              seconds: int = 600, every: float = 5.0, sleep=time.sleep, clock=time.monotonic) -> Result:
    sql = consistency_sql(cfg, fact, dim)
    sample = lambda: tuple(runner.query(sql, identity=identity)[0].values())  # noqa: E731
    before, samples, end = sample(), [], clock() + seconds
    while clock() < end:
        samples.append(sample())
        sleep(every)
    after = sample()
    ok, detail = judge_samples(before, after, samples)
    if before == after:
        ok, detail = False, "no publish changed the tables while sampling; run a publish during the window"
    return Result(7, "publish_consistency", identity, f"{fact.name}+{dim.name}", "old then new, never mixed",
                  detail, ok)


def tenant_identities(cfg: Config) -> list[str]:
    return [cfg.sa(n) for n in TENANT_READERS]
