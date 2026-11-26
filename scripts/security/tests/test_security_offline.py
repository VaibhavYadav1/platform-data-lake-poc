"""Offline tests for the POC D security scripts: no BigQuery, no IAM. Fakes answer the few reads."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest
from google.api_core import exceptions as gexc
from google.auth import exceptions as aexc
from google.cloud.bigquery import SchemaField

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import access_removal as ar  # noqa: E402
import checks  # noqa: E402
import tag_raw_columns as trc  # noqa: E402
from security_lib import Config, PublishedTable, Result, classify, insert_results_sql, result_rows, tenant_tables, write_results  # noqa: E402

CFG = Config(project="proj", env="dev")
A = CFG.sa("sa-tenant-a-user")
FACT = PublishedTable("fct_alert", "alert_date")
DIM = PublishedTable("dim_store", None)


class FakeRunner:
    """Answers by SQL shape. `deny` maps identity -> exception raised for its queries."""

    def __init__(self, deny=None, counts=None, tenants=("ACC00001",), impersonation_denied=True):
        self.calls, self.deny, self.seq = [], deny or {}, 0
        self.counts = counts or {}
        self.tenants = list(tenants)
        self.impersonation_denied = impersonation_denied

    def next_job_id(self):
        self.seq += 1
        return f"job{self.seq}"

    def query(self, sql, identity=None, params=None, job_id=None):
        self.calls.append((sql, identity, params))
        if identity in self.deny:
            raise self.deny[identity]
        if "map_tenant_access" in sql and "principal_hash = TO_HEX(SHA256(LOWER(@p)))" in sql:
            return [{"tenant_id": t} for t in self.tenants]
        if "COUNTIF" in sql:
            return [self.counts.get(("seen", identity), {"n": 5, "other": 0})]
        if "COUNT(*) AS n" in sql:
            return [self.counts.get(("n", identity), {"n": 5})]
        return []

    def impersonate(self, caller, target):
        if self.impersonation_denied and "writer" in target:
            raise aexc.RefreshError("PERMISSION_DENIED: iam.serviceAccounts.getAccessToken")


def forbidden(reason="accessDenied"):
    return gexc.Forbidden("Access Denied", errors=[{"reason": reason}])


# ---------------------------------------------------------------------------------- classify
def test_classify_separates_denied_from_other_errors():
    assert classify(forbidden()) == ("denied", "accessDenied")
    assert classify(forbidden("quotaExceeded"))[0] == "error"
    assert classify(gexc.NotFound("no table"))[0] == "not_found"
    assert classify(gexc.BadRequest("Syntax error"))[0] == "error"
    assert classify(aexc.RefreshError("PERMISSION_DENIED getAccessToken"))[0] == "denied"
    assert classify(ValueError("x"))[0] == "error"


# ---------------------------------------------------------------------------------- cases
def test_case1_passes_when_counts_match_and_no_other_tenant():
    res = checks.case1_isolation(FakeRunner(), CFG, A, [FACT, DIM])
    assert [r.passed for r in res] == [True, True]
    r = FakeRunner()
    checks.case1_isolation(r, CFG, A, [FACT])
    assert "alert_date >= '1970-01-01'" in r.calls[1][0]  # fact needs its partition filter


def test_case1_fails_on_other_tenant_rows_and_on_missing_mapping():
    r = FakeRunner(counts={("seen", A): {"n": 6, "other": 1}})
    assert not checks.case1_isolation(r, CFG, A, [DIM])[0].passed
    assert not checks.case1_isolation(FakeRunner(tenants=()), CFG, A, [DIM])[0].passed


def test_case1_fails_when_the_tenant_has_no_rows_anywhere():
    empty = FakeRunner(counts={("n", None): {"n": 0}, ("seen", A): {"n": 0, "other": 0}})
    res = checks.case1_isolation(empty, CFG, A, [FACT, DIM])
    assert [r.passed for r in res] == [True, True, False]  # 0 = 0 per table, but nothing was really tested
    assert res[-1].actual == "0 rows in every table"


def test_case2_needs_every_statement_denied():
    ok = checks.case2_read_only(FakeRunner(deny={A: forbidden()}), CFG, A, "`c`")
    assert len(ok) == 7 and all(r.passed for r in ok)
    allowed = checks.case2_read_only(FakeRunner(), CFG, A, "`c`")
    assert not any(r.passed for r in allowed)
    syntax = checks.case2_read_only(FakeRunner(deny={A: gexc.BadRequest("Syntax error")}), CFG, A, "`c`")
    assert not any(r.passed for r in syntax)  # an error that isn't a refusal proves nothing


def test_case3_excludes_sec_because_readers_need_it_after_spike1():
    assert "sec" not in checks.upstream_targets(CFG)  # spike 1: readers read the (hashed) mapping table
    assert "sec" in checks.upstream_targets(Config(project="proj", sec_readable=False))
    res = checks.case3_no_upstream(FakeRunner(deny={A: gexc.NotFound("x")}), CFG, A)
    assert not any(r.passed for r in res)  # a missing table is not a denial


def test_case4_writer_denied_and_test_app_control():
    assert checks.case4_no_writer(FakeRunner(), CFG, A).passed
    assert not checks.case4_no_writer(FakeRunner(impersonation_denied=False), CFG, A).passed
    assert all(r.passed for r in checks.case4_test_app_control(FakeRunner(), CFG))


def test_case5_masked_denied_or_leaked():
    probe = CFG.sa("sa-pii-probe")

    class Rows(FakeRunner):
        def __init__(self, rows):
            super().__init__()
            self.rows = rows

        def query(self, sql, identity=None, params=None, job_id=None):
            return self.rows

    assert checks.case5_pii(Rows([{"v": "9f86d081884c7d65"}]), CFG).passed
    assert not checks.case5_pii(Rows([{"v": "contact1@company1.example"}]), CFG).passed
    assert not checks.case5_pii(Rows([]), CFG).passed
    # A probe that cannot read raw_crm at all proves nothing about the tag: fail, don't pass.
    assert not checks.case5_pii(FakeRunner(deny={probe: forbidden()}), CFG).passed

    class TagDenied(FakeRunner):  # untagged column readable, tagged column refused: the tag works
        def query(self, sql, identity=None, params=None, job_id=None):
            if "primary_contact_email" in sql:
                raise forbidden()
            return [{"account_id": "ACC00001"}]

    assert checks.case5_pii(TagDenied(), CFG).passed


def test_case6_adds_probe_store_only_where_the_column_exists():
    r = FakeRunner(counts={("n", A): {"n": 0}})
    res = checks.case6_hidden_rows(r, CFG, A, [FACT, DIM], {"dim_store": {"store_id", "tenant_id"}})
    assert all(x.passed for x in res)
    assert "store_id = @probe" not in r.calls[0][0] and "store_id = @probe" in r.calls[1][0]


def test_case7_judges_old_then_new_never_mixed():
    assert checks.judge_samples((1, 1), (2, 2), [(1, 1), (2, 2), (2, 2)])[0]
    assert not checks.judge_samples((1, 1), (2, 2), [(1, 1), (2, 1)])[0]
    assert not checks.judge_samples((1, 1), (2, 2), [(2, 2), (1, 1)])[0]


# ---------------------------------------------------------------------------------- results
def test_result_rows_and_single_insert():
    res = [Result(2, "read_only", A, "wh INSERT", "denied", "denied (accessDenied)", True, "job1")]
    rows = result_rows("run1", dt.datetime(2026, 11, 24, tzinfo=dt.timezone.utc), res)
    assert rows[0]["job_id"] == "job1" and rows[0]["passed"] is True
    r = FakeRunner()
    write_results(r, CFG, "run1", dt.datetime(2026, 11, 24, tzinfo=dt.timezone.utc), res)
    assert r.calls[0][0].startswith("CREATE TABLE IF NOT EXISTS `proj.ops_dev.security_test_result`")
    assert json.loads(r.calls[1][2]["rows"][1])[0]["case_name"] == "read_only"
    assert "CAST(JSON_VALUE(j, '$.passed') AS BOOL)" in insert_results_sql(CFG)


def test_tenant_tables_from_publish_config():
    names = {t.name: t for t in tenant_tables()}
    assert "dim_date" not in names and "map_tenant_access" not in names
    assert names["fct_alert"].partition_column == "alert_date"


# ---------------------------------------------------------------------------------- access removal
class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_access_removal_passes_within_the_cycle():
    clock, counts = Clock(), iter([40, 40, 40, 0, 0, 40])
    res = ar.run_test(CFG, lambda: next(counts), lambda: None, lambda: None, A,
                      timeout_s=1200, every_s=60, sleep=clock.sleep, clock=clock)
    assert [r.passed for r in res] == [True, True]
    assert res[0].actual == "0 rows after 120 s"


def test_access_removal_times_out_and_refuses_empty_start():
    clock = Clock()
    res = ar.run_test(CFG, lambda: 40, lambda: None, lambda: None, A, timeout_s=300, every_s=60,
                      sleep=clock.sleep, clock=clock)
    assert not res[0].passed
    assert not ar.run_test(CFG, lambda: 0, lambda: None, lambda: None, A)[0].passed


# ---------------------------------------------------------------------------------- tagging
TAG = "projects/p/locations/us-central1/taxonomies/1/policyTags/2"
USERS = [SchemaField("user_id", "STRING"), SchemaField("user_name", "STRING"), SchemaField("email", "STRING")]


def test_plan_schema_tags_only_listed_columns_and_is_idempotent():
    new, changes = trc.plan_schema(USERS, {"user_name": TAG, "email": TAG}, "t")
    assert [c["column"] for c in changes] == ["user_name", "email"]
    assert new[0].policy_tags is None and list(new[1].policy_tags.names) == [TAG]
    again, changes2 = trc.plan_schema(new, {"user_name": TAG, "email": TAG}, "t")
    assert changes2 == []


def test_plan_schema_refuses_missing_column():
    with pytest.raises(trc.TagError, match="not found"):
        trc.plan_schema(USERS, {"phone": TAG}, "t")


def test_indirect_needs_its_tag():
    with pytest.raises(trc.TagError):
        trc.wanted_tags(TAG, None, True)
    assert ("raw_g2", "g2_alert_history") in trc.wanted_tags(TAG, TAG, True)
    assert ("raw_g2", "g2_alert_history") not in trc.wanted_tags(TAG, None, False)


def test_apply_dry_run_changes_nothing():
    class Table:
        def __init__(self, schema):
            self.schema = schema

    class Client:
        def __init__(self):
            self.updated = []
            self.tables = {"p.raw_g2.g2_users": Table(USERS),
                           "p.raw_g2.g2_store_access": Table([SchemaField("principal", "STRING")])}

        def get_table(self, ref):
            return self.tables[ref]

        def update_table(self, table, fields):
            self.updated.append(fields)

    c = Client()
    assert len(trc.apply(c, "p", trc.wanted_tags(TAG, None, False), dry_run=True)) == 3 and c.updated == []
    trc.apply(c, "p", trc.wanted_tags(TAG, None, False), dry_run=False)
    assert c.updated == [["schema"], ["schema"]]
