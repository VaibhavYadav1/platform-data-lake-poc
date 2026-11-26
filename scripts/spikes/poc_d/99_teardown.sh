#!/usr/bin/env bash
# Remove everything the POC D spikes created. Run as yourself, from this folder, when spikes.md is written.
set -uo pipefail
cd "$(dirname "$0")"
set -a; source spike.env; set +a
STATE=spike3/.state
TOKEN=$(gcloud auth print-access-token)

if [ -f "$STATE" ]; then
  source "$STATE"
  if [ -n "${POLICY:-}" ]; then
    echo "== Data policy $POLICY"
    curl -sS -X DELETE "https://bigquerydatapolicy.googleapis.com/v1/$POLICY" -H "Authorization: Bearer $TOKEN"; echo
  fi
  if [ -n "${TAXONOMY:-}" ]; then
    echo "== Taxonomy $TAXONOMY"
    curl -sS -X DELETE "https://datacatalog.googleapis.com/v1/$TAXONOMY" -H "Authorization: Bearer $TOKEN"; echo
  fi
  rm -f "$STATE"
fi

echo "== Datasets (tables, snapshots and row policies go with them)"
bq --project_id "$PROJECT" rm -r -f -d "$PROJECT:spike_rls"
bq --project_id "$PROJECT" rm -r -f -d "$PROJECT:spike_rls_sec"

echo "== Project grants, custom role, service accounts"
for sa in "$SA_READER_A" "$SA_READER_B" "$SA_WRITER" "$SA_MASKED"; do
  gcloud projects remove-iam-policy-binding "$PROJECT" --member "serviceAccount:$sa" \
    --role roles/bigquery.jobUser --condition None --quiet >/dev/null 2>&1
done
gcloud projects remove-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA_WRITER" \
  --role "projects/$PROJECT/roles/spikeRlsWriter" --condition None --quiet >/dev/null 2>&1
gcloud iam roles delete spikeRlsWriter --project "$PROJECT" --quiet
for sa in "$SA_READER_A" "$SA_READER_B" "$SA_WRITER" "$SA_MASKED"; do
  gcloud iam service-accounts delete "$sa" --project "$PROJECT" --quiet
done
echo "Teardown done. A deleted custom role keeps its id reserved for 37 days; use a new name if you rerun."
