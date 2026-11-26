"""
python -m tenant_reader --tenant A --query store_health        (run from apps/, as sa-test-app)

1. Look up the tenant's service account in config.yaml.
2. Impersonate it (google.auth.impersonated_credentials). The caller needs token creator on that account only.
3. Run one query from the catalog below. Values from the command line are always query parameters; table names
   come from config.yaml (project and environment are validated), never from the command line.
4. Print one JSON line per row, then a summary line.

--filter-tenant <id> adds tenant_id = @tenant: tenant A filtering on tenant B's id must return 0 rows.
--impersonate-writer tries to get a token for sa-dwh-writer-<env>; exit 0 only if that is refused.
"""

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SCOPES = ["https://www.googleapis.com/auth/bigquery"]
PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
SA_EMAIL = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z0-9-]+\.iam\.gserviceaccount\.com$")


class ReaderError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    project: str
    env: str
    maximum_bytes_billed: int
    tenants: dict
    writer: str


def load_config(path=HERE / "config.yaml"):
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cfg = Config(raw["project"], raw["environment"], int(raw["maximum_bytes_billed"]),
                 dict(raw["tenants"]), raw["writer"])
    if not PROJECT_ID.match(cfg.project):
        raise ReaderError(f"bad project id {cfg.project!r}")
    if cfg.env not in ("dev", "int"):
        raise ReaderError(f"environment must be dev or int, not {cfg.env!r}")
    for email in [*cfg.tenants.values(), cfg.writer]:
        if not SA_EMAIL.match(email):
            raise ReaderError(f"bad service account email {email!r}")
    return cfg


# name -> (SQL with {wh} for the dataset and an optional {tenant_filter}, required parameters)
CATALOG = {
    # Every store the identity can see, with its tenant. A tenant must see only its own tenant_id.
    "store_health": (
        "SELECT store_id, tenant_id, is_active FROM `{wh}.dim_store` WHERE TRUE{tenant_filter} "
        "ORDER BY store_id LIMIT @limit",
        ("limit",),
    ),
    # Rows per tenant: one line per tenant_id visible to the identity.
    "tenant_summary": (
        "SELECT tenant_id, COUNT(*) AS stores FROM `{wh}.dim_store` WHERE TRUE{tenant_filter} "
        "GROUP BY tenant_id ORDER BY tenant_id",
        (),
    ),
    # Alerts per tenant in a date range; the partition filter that fct_alert requires.
    "alerts": (
        "SELECT tenant_id, COUNT(*) AS alerts FROM `{wh}.fct_alert` "
        "WHERE alert_date BETWEEN @date_from AND @date_to{tenant_filter} GROUP BY tenant_id ORDER BY tenant_id",
        ("date_from", "date_to"),
    ),
}


def build_query(cfg, name, filter_tenant=None, limit=100, date_from=None, date_to=None):
    """SQL text and (name, type, value) parameters. Nothing from the command line is put into the SQL text."""
    if name not in CATALOG:
        raise ReaderError(f"unknown query {name!r}; choose from {sorted(CATALOG)}")
    template, needs = CATALOG[name]
    wh = f"{cfg.project}.wh_{cfg.env}"
    sql = template.format(wh=wh, tenant_filter=" AND tenant_id = @tenant" if filter_tenant is not None else "")
    params = []
    if filter_tenant is not None:
        params.append(("tenant", "STRING", filter_tenant))
    if "limit" in needs:
        params.append(("limit", "INT64", int(limit)))
    if "date_from" in needs:
        today = dt.date.today()
        params.append(("date_from", "DATE", date_from or today - dt.timedelta(days=30)))
        params.append(("date_to", "DATE", date_to or today))
    return sql, params


# ------------------------------------------------------------------------------------- Google Cloud
def impersonate(target, lifetime=300):
    import google.auth
    from google.auth import impersonated_credentials

    source, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return impersonated_credentials.Credentials(source_credentials=source, target_principal=target,
                                                target_scopes=SCOPES, lifetime=lifetime)


def run_query(cfg, credentials, sql, params):
    from google.cloud import bigquery

    client = bigquery.Client(project=cfg.project, credentials=credentials)
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter(n, t, v) for n, t, v in params],
        maximum_bytes_billed=cfg.maximum_bytes_billed,
    )
    job = client.query(sql, job_config=job_config)
    return [dict(r) for r in job.result()], job.job_id


def refresh(credentials):
    from google.auth.transport.requests import Request

    credentials.refresh(Request())


def classify(exc):
    """'refused' when the error means permission denied; anything else is 'error'."""
    text = f"{type(exc).__name__}: {exc}".lower()
    refused = ("permission", "denied", "forbidden", "403", "getaccesstoken", "iam.serviceaccounts")
    return "refused" if any(word in text for word in refused) else "error"


# ------------------------------------------------------------------------------------- command line
def parse_args(argv):
    p = argparse.ArgumentParser(prog="python -m tenant_reader", description=__doc__.split("\n\n")[0])
    p.add_argument("--tenant", help="A or B (from config.yaml)")
    p.add_argument("--query", default="store_health", choices=sorted(CATALOG))
    p.add_argument("--filter-tenant", help="add tenant_id = @tenant (negative case: another tenant's id)")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--date-from", type=dt.date.fromisoformat)
    p.add_argument("--date-to", type=dt.date.fromisoformat)
    p.add_argument("--impersonate-writer", action="store_true",
                   help="negative case: try to get a token for the writer; passes only if refused")
    p.add_argument("--config", type=Path, default=HERE / "config.yaml")
    args = p.parse_args(argv)
    if not args.impersonate_writer and not args.tenant:
        p.error("--tenant is required (or use --impersonate-writer)")
    return args


def emit(**fields):
    print(json.dumps(fields, default=str))


def main(argv=None, impersonate_fn=impersonate, run_fn=run_query, refresh_fn=refresh):
    args = parse_args(argv)
    try:
        cfg = load_config(args.config)
    except (ReaderError, KeyError, OSError) as e:
        emit(event="CONFIG_ERROR", message=str(e))
        return 2

    if args.impersonate_writer:
        try:
            refresh_fn(impersonate_fn(cfg.writer))
        except Exception as e:  # noqa: BLE001 - any failure is classified below
            outcome = classify(e)
            emit(event="WRITER_IMPERSONATION", target=cfg.writer, outcome=outcome, message=str(e)[:300])
            return 0 if outcome == "refused" else 1
        emit(event="WRITER_IMPERSONATION", target=cfg.writer, outcome="ALLOWED",
             message="security failure: the caller can act as the writer")
        return 1

    if args.tenant not in cfg.tenants:
        emit(event="CONFIG_ERROR", message=f"unknown tenant {args.tenant!r}; config has {sorted(cfg.tenants)}")
        return 2
    target = cfg.tenants[args.tenant]
    try:
        sql, params = build_query(cfg, args.query, args.filter_tenant, args.limit, args.date_from, args.date_to)
        rows, job_id = run_fn(cfg, impersonate_fn(target), sql, params)
    except Exception as e:  # noqa: BLE001
        emit(event="QUERY_FAILED", tenant=args.tenant, identity=target, outcome=classify(e), message=str(e)[:300])
        return 1
    for row in rows:
        emit(**row)
    emit(event="DONE", tenant=args.tenant, identity=target, query=args.query, rows=len(rows),
         tenants_seen=sorted({r.get("tenant_id") for r in rows if "tenant_id" in r}, key=str), job_id=job_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
