"""Shared pieces of the POC D security scripts (D5, D6): identities, impersonated BigQuery access,
classification of "denied" versus other errors, and the results table.

Why a separate module: the pytest suite (test_access.py) and the access-removal test (access_removal.py) must
judge "denied" the same way and write the same result rows, so D8 can link every attempt to its audit log entry.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TABLES_YAML = REPO / "orchestration" / "publish" / "tables.yaml"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Plan section 4.4, plus sa-pii-probe (design section 4.1): reader identity -> tenant letter.
TENANT_READERS = {
    "sa-tenant-a-user": "A",
    "sa-tenant-b-user": "B",
    "sa-app-tenant-a": "A",
    "sa-app-tenant-b": "B",
}
TEST_APP = "sa-test-app"
PII_PROBE = "sa-pii-probe"


def log(event: str, severity: str = "INFO", **fields) -> None:
    print(json.dumps({"severity": severity, "event": event, **fields}, default=str), flush=True)


@dataclass(frozen=True)
class Config:
    project: str = "gks-datalake-poc2-dev"
    env: str = "dev"
    location: str = "us-central1"
    max_bytes: int = 1_000_000_000  # every query is capped; a security test never needs more than 1 GB
    tenants: dict = field(default_factory=lambda: {"A": "ACC00001", "B": "ACC00005"})
    vendor_account: str = "ACC00031"
    probe_store: str = "S999"
    sec_readable: bool = True  # spike 1: readers need viewer on sec_{env} (the mapping holds only hashes)

    @classmethod
    def from_env(cls, env=None) -> "Config":
        e = os.environ if env is None else env
        return cls(
            project=e.get("PROJECT", "gks-datalake-poc2-dev"),
            env=e.get("ENV", "dev"),
            location=e.get("LOCATION", "us-central1"),
            tenants={"A": e.get("TENANT_A", "ACC00001"), "B": e.get("TENANT_B", "ACC00005")},
            vendor_account=e.get("VENDOR_ACCOUNT", "ACC00031"),
            probe_store=e.get("PROBE_STORE", "S999"),
            sec_readable=e.get("SEC_READABLE", "1") == "1",
        )

    def ds(self, layer: str) -> str:
        return f"{layer}_{self.env}"

    def table(self, layer: str, name: str) -> str:
        return f"`{self.project}.{self.ds(layer)}.{name}`"

    def sa(self, name: str) -> str:
        return f"{name}@{self.project}.iam.gserviceaccount.com"

    @property
    def writer(self) -> str:
        return self.sa(f"sa-dwh-writer-{self.env}")

    @property
    def results_table(self) -> str:
        return self.table("ops", "security_test_result")


@dataclass(frozen=True)
class PublishedTable:
    name: str
    partition_column: str | None

    def where(self) -> str:
        """Facts in wh require a partition filter; a wide range satisfies it and still counts every row."""
        return f" WHERE {self.partition_column} >= '1970-01-01'" if self.partition_column else ""

    def and_(self) -> str:
        return " AND" if self.partition_column else " WHERE"


def tenant_tables(path: Path = TABLES_YAML) -> list[PublishedTable]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [
        PublishedTable(t["name"], t.get("partition_column"))
        for t in raw.get("tables") or []
        if t.get("tenant_scoped") and t.get("dataset", "wh") == "wh"
    ]


# ------------------------------------------------------------------------------ outcomes
@dataclass
class Outcome:
    kind: str  # ok | denied | not_found | error
    rows: list = field(default_factory=list)
    job_id: str | None = None
    reason: str = ""
    message: str = ""


def classify(exc: Exception) -> tuple[str, str]:
    """(kind, reason). Only a real permission refusal counts as denied: a syntax error or a missing table must
    not make a security test pass."""
    from google.api_core import exceptions as gexc

    if isinstance(exc, gexc.Forbidden):
        reasons = [e.get("reason", "") for e in (getattr(exc, "errors", None) or []) if isinstance(e, dict)]
        reason = reasons[0] if reasons else "forbidden"
        if reason in ("quotaExceeded", "rateLimitExceeded", "billingNotEnabled"):
            return "error", reason
        return "denied", reason
    if isinstance(exc, gexc.NotFound):
        return "not_found", "notFound"
    try:
        from google.auth import exceptions as aexc

        if isinstance(exc, aexc.RefreshError):
            text = str(exc)
            if "PERMISSION_DENIED" in text or "getAccessToken" in text or "403" in text:
                return "denied", "iam.serviceAccounts.getAccessToken"
            return "error", "refresh"
    except ImportError:  # pragma: no cover
        pass
    return "error", type(exc).__name__


def attempt(fn, job_id: str | None = None) -> Outcome:
    try:
        return Outcome("ok", rows=fn() or [], job_id=job_id)
    except Exception as exc:  # noqa: BLE001  - classified, never swallowed silently
        kind, reason = classify(exc)
        return Outcome(kind, job_id=job_id, reason=reason, message=str(exc)[:500])


# ------------------------------------------------------------------------------ BigQuery access
class BigQueryRunner:
    """Runs SQL as the caller (identity=None) or as an impersonated service account.

    Each query gets an explicit job id, so even a refused job can be found in JOBS_BY_PROJECT and the audit logs
    (D8). Parameters are {name: (TYPE, value-or-list)}, as in publish.py.
    """

    def __init__(self, cfg: Config, run_id: str):
        import google.auth
        from google.cloud import bigquery

        self._bq = bigquery
        self.cfg = cfg
        self.run_id = run_id
        self._seq = 0
        self._source, _ = google.auth.default(scopes=SCOPES)
        self._clients: dict = {}

    def credentials(self, identity: str | None, source=None):
        from google.auth import impersonated_credentials

        if identity is None:
            return self._source
        return impersonated_credentials.Credentials(
            source_credentials=source or self._source, target_principal=identity, target_scopes=SCOPES, lifetime=900
        )

    def _client(self, identity):
        if identity not in self._clients:
            self._clients[identity] = self._bq.Client(
                project=self.cfg.project, credentials=self.credentials(identity), location=self.cfg.location
            )
        return self._clients[identity]

    def next_job_id(self) -> str:
        self._seq += 1
        return f"sec_{self.run_id}_{self._seq:04d}"

    def query(self, sql: str, identity: str | None = None, params: dict | None = None, job_id: str | None = None):
        bq = self._bq
        built = []
        for name, (typ, value) in (params or {}).items():
            if isinstance(value, list):
                built.append(bq.ArrayQueryParameter(name, typ, value))
            else:
                built.append(bq.ScalarQueryParameter(name, typ, value))
        cfg = bq.QueryJobConfig(query_parameters=built, maximum_bytes_billed=self.cfg.max_bytes)
        job = self._client(identity).query(sql, job_config=cfg, job_id=job_id or self.next_job_id())
        return [dict(r) for r in job.result()]

    def impersonate(self, caller: str | None, target: str) -> None:
        """Ask for a token for `target` while acting as `caller`. Raises RefreshError when IAM refuses."""
        from google.auth.transport.requests import Request

        creds = self.credentials(target, source=self.credentials(caller))
        creds.refresh(Request())


def run(runner, sql: str, identity: str | None = None, params: dict | None = None) -> Outcome:
    job_id = runner.next_job_id()
    return attempt(lambda: runner.query(sql, identity=identity, params=params, job_id=job_id), job_id)


# ------------------------------------------------------------------------------ results
RESULT_COLUMNS = [
    ("run_id", "STRING"), ("run_at", "TIMESTAMP"), ("case_no", "INT64"), ("case_name", "STRING"),
    ("identity", "STRING"), ("target", "STRING"), ("expected", "STRING"), ("actual", "STRING"),
    ("passed", "BOOL"), ("job_id", "STRING"), ("detail", "STRING"),
]


@dataclass
class Result:
    case_no: int
    case_name: str
    identity: str
    target: str
    expected: str
    actual: str
    passed: bool
    job_id: str | None = None
    detail: str = ""


def new_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6]


def result_rows(run_id: str, run_at: dt.datetime, results: list[Result]) -> list[dict]:
    return [
        {"run_id": run_id, "run_at": run_at.isoformat(), "case_no": r.case_no, "case_name": r.case_name,
         "identity": r.identity, "target": r.target, "expected": r.expected, "actual": r.actual,
         "passed": r.passed, "job_id": r.job_id, "detail": r.detail[:1000]}
        for r in results
    ]


def create_results_sql(cfg: Config) -> str:
    cols = ", ".join(f"{c} {t}" for c, t in RESULT_COLUMNS)
    return f"CREATE TABLE IF NOT EXISTS {cfg.results_table} ({cols}) PARTITION BY DATE(run_at)"


def insert_results_sql(cfg: Config) -> str:
    """The rows travel as one JSON parameter, so the statement text never contains test data."""
    cols = ", ".join(c for c, _ in RESULT_COLUMNS)

    def value(c, t):
        v = f"JSON_VALUE(j, '$.{c}')"
        return v if t == "STRING" else f"TIMESTAMP({v})" if t == "TIMESTAMP" else f"CAST({v} AS {t})"

    select = ", ".join(value(c, t) for c, t in RESULT_COLUMNS)
    return f"INSERT INTO {cfg.results_table} ({cols}) SELECT {select} FROM UNNEST(JSON_QUERY_ARRAY(@rows)) AS j"


def write_results(runner, cfg: Config, run_id: str, run_at: dt.datetime, results: list[Result]) -> None:
    """One INSERT for the whole run, as the runner (it needs editor on ops_{env})."""
    if not results:
        return
    runner.query(create_results_sql(cfg))
    rows = result_rows(run_id, run_at, results)
    runner.query(insert_results_sql(cfg), params={"rows": ("STRING", json.dumps(rows))})
    log("RESULTS_WRITTEN", run_id=run_id, rows=len(rows), passed=sum(r.passed for r in results))
