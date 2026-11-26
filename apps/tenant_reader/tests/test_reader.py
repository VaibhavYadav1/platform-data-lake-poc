"""tenant_reader without Google Cloud: fakes stand in for impersonation and BigQuery."""

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # apps/
from tenant_reader import reader as r  # noqa: E402

CFG = r.load_config()


def test_config_in_repo_is_valid():
    assert CFG.env == "dev" and set(CFG.tenants) == {"A", "B"}
    assert CFG.tenants["A"].startswith("sa-app-tenant-a@") and CFG.writer.startswith("sa-dwh-writer-dev@")


def test_every_query_reads_wh_only_and_binds_parameters():
    for name in r.CATALOG:
        sql, params = r.build_query(CFG, name, filter_tenant="ACC00005")
        assert "`gks-datalake-poc2-dev.wh_dev." in sql and "{" not in sql
        assert "tenant_id = @tenant" in sql and ("tenant", "STRING", "ACC00005") in params
        assert "ACC00005" not in sql


def test_injection_attempt_stays_a_parameter():
    evil = "x' OR TRUE --"
    sql, params = r.build_query(CFG, "store_health", filter_tenant=evil)
    assert evil not in sql and ("tenant", "STRING", evil) in params


def test_alerts_has_the_partition_filter():
    sql, params = r.build_query(CFG, "alerts", date_from=dt.date(2026, 11, 1), date_to=dt.date(2026, 11, 2))
    assert "alert_date BETWEEN @date_from AND @date_to" in sql
    assert ("date_from", "DATE", dt.date(2026, 11, 1)) in params and "@tenant" not in sql


def test_unknown_query_is_refused():
    with pytest.raises(r.ReaderError):
        r.build_query(CFG, "drop_everything")


@pytest.mark.parametrize("message,expected", [
    ("403 Permission 'iam.serviceAccounts.getAccessToken' denied", "refused"),
    ("Access Denied: Table wh_dev.dim_store", "refused"),
    ("Forbidden", "refused"),
    ("Deadline exceeded", "error"),
])
def test_classify(message, expected):
    assert r.classify(RuntimeError(message)) == expected


def run_main(argv, capsys, rows=(), fail=None, refresh_error=None):
    seen = {}

    def impersonate(target):
        seen["target"] = target
        return f"creds-for-{target}"

    def run(cfg, creds, sql, params):
        seen.update(creds=creds, sql=sql, params=params)
        if fail:
            raise fail
        return list(rows), "job-1"

    def refresh(creds):
        if refresh_error:
            raise refresh_error

    code = r.main(argv, impersonate_fn=impersonate, run_fn=run, refresh_fn=refresh)
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    return code, lines, seen


def test_tenant_a_runs_as_its_app_identity(capsys):
    code, lines, seen = run_main(["--tenant", "A", "--query", "store_health"], capsys,
                                 rows=[{"store_id": "S1", "tenant_id": "ACC00001", "is_active": True}])
    assert code == 0 and seen["target"] == CFG.tenants["A"]
    assert lines[-1]["event"] == "DONE" and lines[-1]["tenants_seen"] == ["ACC00001"] and lines[-1]["rows"] == 1


def test_filter_on_another_tenant_returns_zero_rows(capsys):
    code, lines, seen = run_main(["--tenant", "A", "--query", "store_health", "--filter-tenant", "ACC00005"], capsys)
    assert code == 0 and lines[-1]["rows"] == 0 and ("tenant", "STRING", "ACC00005") in seen["params"]


def test_writer_impersonation_refused_passes(capsys):
    code, lines, _ = run_main(["--impersonate-writer"], capsys,
                              refresh_error=RuntimeError("403 iam.serviceAccounts.getAccessToken denied"))
    assert code == 0 and lines[0]["outcome"] == "refused"


def test_writer_impersonation_allowed_fails(capsys):
    code, lines, _ = run_main(["--impersonate-writer"], capsys)
    assert code == 1 and lines[0]["outcome"] == "ALLOWED"


def test_query_denied_is_reported(capsys):
    code, lines, _ = run_main(["--tenant", "B"], capsys, fail=RuntimeError("Access Denied"))
    assert code == 1 and lines[0]["event"] == "QUERY_FAILED" and lines[0]["outcome"] == "refused"


def test_unknown_tenant(capsys):
    code, lines, _ = run_main(["--tenant", "C"], capsys)
    assert code == 2 and lines[0]["event"] == "CONFIG_ERROR"
