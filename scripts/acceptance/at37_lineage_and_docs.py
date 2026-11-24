#!/usr/bin/env python3
"""AT-37: lineage and docs (E10).

Passes when ALL of these hold for one environment:
  1. The Data Lineage API is enabled.
  2. Lineage for wh_<env>.fct_alert runs upstream through build_<env> to raw_g2.
  3. The dbt docs page exists at gs://<project>-dbt-docs/<env>/index.html.
  4. Every model in the docs' manifest.json has a description.

Run:  python scripts/acceptance/at37_lineage_and_docs.py --env dev [--project P] [--location L]

Lineage appears only after jobs have run, so run a micro-batch first. The console (BigQuery, the
table, Lineage tab) is the picture to keep as evidence; this script is the check that the same
edges exist. Needs: google-cloud-datacatalog-lineage, google-cloud-storage, google-cloud-service-usage.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

MAX_DEPTH = 6  # wh <- build <- (staging, intermediate) <- raw_g2 is at most a handful of hops
MIN_DOCS_KB = 10  # a docs page smaller than this is empty or broken


# ----------------------------------------------------------------------------- pure checks
def fqn(project: str, dataset: str, table: str) -> str:
    return f"bigquery:{project}.{dataset}.{table}"


def dataset_of(name: str) -> str:
    """'bigquery:proj.dataset.table' -> 'dataset'."""
    return name.split(":", 1)[-1].split(".")[1]


def upstream(links_into, start: str, max_depth: int = MAX_DEPTH) -> set[str]:
    """Every table that feeds `start`, found hop by hop. links_into(name) -> source names."""
    seen, frontier = {start}, [start]
    for _ in range(max_depth):
        nxt = []
        for name in frontier:
            for source in links_into(name):
                if source not in seen:
                    seen.add(source)
                    nxt.append(source)
        frontier = nxt
        if not frontier:
            break
    return seen


def lineage_problems(links_into, project: str, env: str, table: str = "fct_alert") -> list[str]:
    """What is missing from the chain raw_g2 -> build_<env> -> wh_<env> for `table`."""
    start = fqn(project, f"wh_{env}", table)
    feeds = upstream(links_into, start)
    datasets = {dataset_of(n) for n in feeds}
    problems = []
    if f"build_{env}" not in datasets:
        problems.append(f"no lineage from build_{env} into wh_{env}.{table}")
    if "raw_g2" not in datasets:
        problems.append(f"no lineage from raw_g2 upstream of wh_{env}.{table}")
    return problems


def models_without_description(manifest: dict) -> tuple[int, list[str]]:
    """(number of models, names of those whose description is empty)."""
    models = [n for n in manifest.get("nodes", {}).values() if n.get("resource_type") == "model"]
    missing = sorted(n["name"] for n in models if not (n.get("description") or "").strip())
    return len(models), missing


# ------------------------------------------------------------------------- cloud access
def lineage_links_into(project: str, location: str):
    """links_into(name) backed by the Data Lineage API (search for links that end at `name`)."""
    from google.cloud import datacatalog_lineage_v1 as lineage

    client = lineage.LineageClient()

    def links_into(name: str) -> list[str]:
        request = lineage.SearchLinksRequest(
            parent=f"projects/{project}/locations/{location}",
            target=lineage.EntityReference(fully_qualified_name=name),
        )
        return [link.source.fully_qualified_name for link in client.search_links(request=request)]

    return links_into


def lineage_api_enabled(project: str) -> bool:
    from google.cloud import service_usage_v1

    service = service_usage_v1.ServiceUsageClient().get_service(
        name=f"projects/{project}/services/datalineage.googleapis.com"
    )
    return service.state == service_usage_v1.State.ENABLED


def read_docs(project: str, env: str):
    """(page bytes or None, manifest dict or None) from the docs bucket."""
    from google.cloud import storage

    bucket = storage.Client(project=project).bucket(f"{project}-dbt-docs")
    page, manifest = bucket.blob(f"{env}/index.html"), bucket.blob(f"{env}/manifest.json")
    return (
        page.download_as_bytes() if page.exists() else None,
        json.loads(manifest.download_as_text()) if manifest.exists() else None,
    )


# --------------------------------------------------------------------------------- the test
def run(project: str, env: str, location: str, links_into, api_enabled, docs) -> list[str]:
    """All the failures, or an empty list for a pass. The three cloud calls are passed in."""
    failures = []

    if not api_enabled:
        failures.append("the Data Lineage API is not enabled (terraform/shared/lineage.tf)")

    failures += lineage_problems(links_into, project, env)

    page, manifest = docs
    if page is None:
        failures.append(f"no docs page at gs://{project}-dbt-docs/{env}/index.html (cloudbuild/main.yaml)")
    elif len(page) / 1024 < MIN_DOCS_KB:
        failures.append(f"the docs page is only {len(page) / 1024:.1f} KB: empty or broken")

    if manifest is None:
        failures.append(f"no manifest.json at gs://{project}-dbt-docs/{env}/ (cloudbuild/main.yaml)")
    else:
        count, missing = models_without_description(manifest)
        if count == 0:
            failures.append("the manifest holds no models")
        if missing:
            failures.append(f"{len(missing)} of {count} models have no description: {', '.join(missing)}")
    return failures


def default_project() -> str:
    out = subprocess.run(["gcloud", "config", "get-value", "project"], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AT-37: lineage and docs")
    ap.add_argument("--env", required=True, choices=["dev", "int"])
    ap.add_argument("--project", help="default: the gcloud project")
    ap.add_argument("--location", default="us-central1", help="location of the lineage data")
    args = ap.parse_args(argv)

    project = args.project or default_project()
    print(f"AT-37 for {args.env} in {project}")
    failures = run(
        project,
        args.env,
        args.location,
        lineage_links_into(project, args.location),
        lineage_api_enabled(project),
        read_docs(project, args.env),
    )
    for f in failures:
        print(f"  FAIL: {f}")
    if failures:
        print("AT-37 FAILED. Lineage only appears after a micro-batch has run; docs only after a deploy.")
        return 1
    print("AT-37 PASSED")
    print(f"  docs: https://storage.cloud.google.com/{project}-dbt-docs/{args.env}/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
