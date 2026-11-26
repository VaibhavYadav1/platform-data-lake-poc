"""Run the parity queries (C4, AT-26a) and print what each one finds.

    python run_parity.py --project gks-datalake-poc2-dev --user yugensys [--only fct_alert] [--rows 10]

Fills the placeholders in each .sql file, runs it in BigQuery and prints the number of rows. Zero is parity.
Each file puts 'only_in_poc1' / 'only_in_poc2' in its first column, so the output shows which side differs.
Needs `google-cloud-bigquery` (installed with dbt-bigquery) and read access to the baseline project.
"""
import argparse
from pathlib import Path

from google.cloud import bigquery

HERE = Path(__file__).resolve().parent
BASELINE_PROJECT = "data-lake-poc-512405"   # holds poc1_baseline (docs/poc2/baseline.md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="POC 2 project that holds dbt_<user>_build")
    ap.add_argument("--user", required=True, help="your DBT_USER")
    ap.add_argument("--baseline-project", default=BASELINE_PROJECT)
    ap.add_argument("--only", help="run one file, for example fct_alert")
    ap.add_argument("--rows", type=int, default=5, help="rows to print per file")
    args = ap.parse_args()

    client = bigquery.Client(project=args.project, location="us-central1")
    files = sorted(HERE.glob("*.sql"))
    if args.only:
        files = [f for f in files if f.stem == args.only]
    failed = 0
    for f in files:
        sql = (f.read_text(encoding="utf-8")
               .replace("{baseline_project}", args.baseline_project)
               .replace("{project}", args.project)
               .replace("{user}", args.user))
        print(f"\n=== {f.stem}")
        try:
            rows = list(client.query(sql).result())
        except Exception as e:                      # a bad column name or missing table lands here
            failed += 1
            print("  ERROR:", str(e).splitlines()[0][:300])
            continue
        sides = {}
        for r in rows:
            side = r[0] if len(r) and isinstance(r[0], str) and r[0].startswith("only_in") else "row"
            sides[side] = sides.get(side, 0) + 1
        print(f"  {len(rows)} difference rows {sides if rows else '-> PARITY'}")
        for r in rows[: args.rows]:
            print("   ", dict(r.items()))
    print(f"\n{len(files)} files, {failed} errored")


if __name__ == "__main__":
    main()
