#!/usr/bin/env bash
# The commands of poc-dbt-runner-<env> (E3). The Cloud Run job passes one of:
#
#   microbatch          dbt build --exclude tag:daily, then publish.py (it logs PUBLISH_SKIPPED if dbt did not exit 0)
#   fullload            the daily full rebuild: orchestration/publish/full_load.py
#   dbt <arguments>     any dbt command, for example: dbt source freshness --target dev
#                       or, one time after a clean CRM start: dbt run --full-refresh -s int_crm__account int_crm__store int_account__tenant
#
# The environment comes from the job: DBT_TARGET (dev or int) and GCP_PROJECT. Exit code 0 only if every step worked,
# so the workflow fails (and the "failed poc-* workflow" alert fires) when anything did not.
set -u
cd /app/dbt
TARGET="${DBT_TARGET:-dev}"
PUBLISH=/app/orchestration/publish

case "${1:-}" in
  microbatch)
    dbt build --exclude tag:daily --target "$TARGET"
    dbt_rc=$?
    python "$PUBLISH/publish.py" --env "$TARGET" --dbt-exit-code "$dbt_rc"
    publish_rc=$?
    # dbt failed: that is the exit code (publish only logged that it skipped). dbt passed: publish decides.
    if [ "$dbt_rc" -ne 0 ]; then exit "$dbt_rc"; fi
    exit "$publish_rc"
    ;;
  fullload)
    exec python "$PUBLISH/full_load.py"
    ;;
  dbt)
    exec "$@"
    ;;
  *)
    echo "usage: entrypoint.sh microbatch | fullload | dbt <arguments>" >&2
    exit 2
    ;;
esac
