"""D5 security suite (AT-24 command-line part, AT-27, AT-28 case 5). Runs against real BigQuery.

    set RUN_SECURITY_SUITE=1      (and PROJECT, ENV if not gks-datalake-poc2-dev / dev)
    pytest scripts/security/test_access.py -v
    # case 7 needs a publish running during the window:  RUN_PUBLISH_CONSISTENCY=1

Every check writes a row to ops_{env}.security_test_result, with the job id D8 links to the audit logs.
The runner must: be in rls_all_rows (internal counts), read sec_{env}, write ops_{env} and wh_{env} (canary table),
and hold token creator on the test identities (Terraform variable security_test_runners), never on the writer.
"""
import datetime as dt
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks  # noqa: E402
from security_lib import PII_PROBE, TEST_APP, BigQueryRunner, Config, log, new_run_id, tenant_tables, write_results  # noqa: E402

pytestmark = pytest.mark.skipif(os.environ.get("RUN_SECURITY_SUITE") != "1",
                                reason="security suite runs against BigQuery; set RUN_SECURITY_SUITE=1")

CFG = Config.from_env()
TENANT_IDS = checks.tenant_identities(CFG)
READERS = TENANT_IDS + [CFG.sa(PII_PROBE)]


@pytest.fixture(scope="session")
def session():
    run_id, run_at = new_run_id(), dt.datetime.now(dt.timezone.utc)
    runner = BigQueryRunner(CFG, run_id)
    state = {"runner": runner, "results": [], "tables": tenant_tables()}
    log("SECURITY_SUITE_START", run_id=run_id, project=CFG.project, env=CFG.env)
    yield state
    write_results(runner, CFG, run_id, run_at, state["results"])


def _record(session, results):
    results = results if isinstance(results, list) else [results]
    session["results"].extend(results)
    failed = [r for r in results if not r.passed]
    assert not failed, "\n".join(f"{r.target}: expected {r.expected}, got {r.actual} {r.detail}" for r in failed)


@pytest.mark.parametrize("identity", TENANT_IDS)
def test_case1_each_tenant_sees_all_and_only_its_rows(session, identity):
    _record(session, checks.case1_isolation(session["runner"], CFG, identity, session["tables"]))


@pytest.mark.parametrize("identity", READERS)
def test_case2_readers_cannot_write_or_change_tables(session, identity):
    canary = checks.ensure_canary(session["runner"], CFG)
    _record(session, checks.case2_read_only(session["runner"], CFG, identity, canary))


@pytest.mark.parametrize("identity", READERS)
def test_case3_readers_cannot_read_upstream_datasets(session, identity):
    _record(session, checks.case3_no_upstream(session["runner"], CFG, identity))


@pytest.mark.parametrize("identity", READERS + [CFG.sa(TEST_APP)])
def test_case4_nobody_can_impersonate_the_writer(session, identity):
    _record(session, checks.case4_no_writer(session["runner"], CFG, identity))


def test_case4_test_app_reaches_only_its_app_identities(session):
    _record(session, checks.case4_test_app_control(session["runner"], CFG))


def test_case5_raw_contact_email_masked_or_denied(session):
    _record(session, checks.case5_pii(session["runner"], CFG))


@pytest.mark.parametrize("identity", TENANT_IDS)
def test_case6_null_vendor_and_probe_rows_hidden(session, identity):
    cols = checks.wh_columns(session["runner"], CFG)
    _record(session, checks.case6_hidden_rows(session["runner"], CFG, identity, session["tables"], cols))


@pytest.mark.skipif(os.environ.get("RUN_PUBLISH_CONSISTENCY") != "1",
                    reason="needs a publish running during the window; set RUN_PUBLISH_CONSISTENCY=1")
def test_case7_publish_is_never_seen_half_done(session):
    by_name = {t.name: t for t in session["tables"]}
    _record(session, checks.case7_publish_consistency(
        session["runner"], CFG, TENANT_IDS[0], by_name["fct_alert"], by_name["dim_store"],
        seconds=int(os.environ.get("CONSISTENCY_SECONDS", "600"))))
