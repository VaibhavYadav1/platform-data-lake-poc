"""Run one SQL file in BigQuery as yourself or as an impersonated service account, and report the outcome.

    python run_as.py [--as SA_EMAIL] [--expect ok|error|denied] [--param NAME=TYPE:VALUE ...] FILE.sql

- ${NAME} placeholders in the file are filled from environment variables (source spike.env first).
- --param adds a query parameter. TYPE is a BigQuery type; TYPE[] makes an array with comma-separated values,
  e.g. --param dates=DATE[]:2026-11-03,2026-11-04
- --expect prints PASS or FAIL against what the spike expects, so the output can go straight into spikes.md.
- Impersonating needs roles/iam.serviceAccountTokenCreator on the target (00_setup.sh grants it). New grants can take
  a few minutes to work.

The same pattern (google.auth.impersonated_credentials) is what the D5 security suite will use.
"""

import argparse
import os
import string
import sys
import time

import google.auth
from google.api_core import exceptions
from google.auth import impersonated_credentials
from google.cloud import bigquery

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
MAX_ROWS = 50


def credentials_for(service_account):
    source, _ = google.auth.default(scopes=SCOPES)
    if not service_account:
        return source
    return impersonated_credentials.Credentials(
        source_credentials=source, target_principal=service_account, target_scopes=SCOPES, lifetime=900)


def parse_param(text):
    name, _, typed = text.partition("=")
    kind, _, value = typed.partition(":")
    if not name or not kind:
        raise SystemExit(f"bad --param {text!r}; use NAME=TYPE:VALUE")
    if kind.endswith("[]"):
        return bigquery.ArrayQueryParameter(name, kind[:-2], value.split(",") if value else [])
    return bigquery.ScalarQueryParameter(name, kind, value)


def error_reason(exc):
    errors = getattr(exc, "errors", None) or []
    return errors[0].get("reason", "") if errors else type(exc).__name__


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file")
    parser.add_argument("--as", dest="service_account", default="", help="service account to impersonate")
    parser.add_argument("--expect", choices=("ok", "error", "denied"), help="what the spike expects")
    parser.add_argument("--param", action="append", default=[], help="NAME=TYPE:VALUE or NAME=TYPE[]:V1,V2")
    args = parser.parse_args()

    with open(args.file, encoding="utf-8") as handle:
        sql = string.Template(handle.read()).substitute(os.environ)  # a missing variable stops here, by design

    project = os.environ["PROJECT"]
    client = bigquery.Client(project=project, location=os.environ.get("LOCATION", "us-central1"),
                             credentials=credentials_for(args.service_account))
    config = bigquery.QueryJobConfig(use_query_cache=False,
                                     query_parameters=[parse_param(p) for p in args.param])

    who = args.service_account or "you (application default credentials)"
    print(f"== {os.path.basename(args.file)} as {who}")
    started = time.monotonic()
    outcome = "ok"
    try:
        job = client.query(sql, job_config=config)
        rows = list(job.result(max_results=MAX_ROWS))
        elapsed = time.monotonic() - started
        print(f"   job {job.job_id}  {elapsed:.1f}s  billed {job.total_bytes_billed or 0} bytes")
        if rows:
            print("   " + " | ".join(rows[0].keys()))
            for row in rows:
                print("   " + " | ".join("NULL" if v is None else str(v) for v in row.values()))
        else:
            print("   (no rows)")
    except exceptions.GoogleAPICallError as exc:
        reason = error_reason(exc)
        outcome = "denied" if reason == "accessDenied" or exc.code == 403 else "error"
        print(f"   {outcome.upper()}  reason={reason}  code={exc.code}")
        print(f"   {exc.message}")

    if args.expect:
        passed = outcome == args.expect or (args.expect == "error" and outcome == "denied")
        print(f"   {'PASS' if passed else 'FAIL'} (expected {args.expect}, got {outcome})")
        sys.exit(0 if passed else 1)
    sys.exit(0 if outcome == "ok" else 2)


if __name__ == "__main__":
    main()
