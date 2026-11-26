#!/usr/bin/env bash
# POC D spikes: service accounts, custom role and project grants. Run once, as yourself, from this folder.
# Needs: iam.serviceAccounts.create, iam.roles.create, resourcemanager.projects.setIamPolicy, serviceusage.
set -euo pipefail
cd "$(dirname "$0")"
set -a; source spike.env; set +a

echo "== APIs"
gcloud services enable bigquery.googleapis.com iamcredentials.googleapis.com datacatalog.googleapis.com \
  bigquerydatapolicy.googleapis.com --project "$PROJECT"

echo "== Service accounts"
for sa in spike-reader-a spike-reader-b spike-writer spike-masked; do
  gcloud iam service-accounts describe "$sa@$PROJECT.iam.gserviceaccount.com" --project "$PROJECT" >/dev/null 2>&1 \
    || gcloud iam service-accounts create "$sa" --project "$PROJECT" --display-name "POC D spike: $sa"
done

echo "== You may impersonate them"
for sa in "$SA_READER_A" "$SA_READER_B" "$SA_WRITER" "$SA_MASKED"; do
  gcloud iam service-accounts add-iam-policy-binding "$sa" --project "$PROJECT" \
    --member "user:$ME" --role roles/iam.serviceAccountTokenCreator --condition None >/dev/null
done

echo "== Job user for all four"
for sa in "$SA_READER_A" "$SA_READER_B" "$SA_WRITER" "$SA_MASKED"; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$sa" \
    --role roles/bigquery.jobUser --condition None >/dev/null
done

echo "== Custom role for the writer (the candidate pocDwhWriterRls)"
PERMS=bigquery.rowAccessPolicies.create,bigquery.rowAccessPolicies.delete,bigquery.rowAccessPolicies.get,\
bigquery.rowAccessPolicies.getIamPolicy,bigquery.rowAccessPolicies.list,bigquery.rowAccessPolicies.setIamPolicy,\
bigquery.rowAccessPolicies.update
gcloud iam roles create spikeRlsWriter --project "$PROJECT" --title "POC D spike RLS writer" \
  --permissions "$PERMS" --stage GA 2>/dev/null \
  || gcloud iam roles update spikeRlsWriter --project "$PROJECT" --permissions "$PERMS" --quiet >/dev/null
# Project level for the spike. D2 tries the dataset level; record in spikes.md whether that works.
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA_WRITER" \
  --role "projects/$PROJECT/roles/spikeRlsWriter" --condition None >/dev/null

echo "== Datasets, tables, dataset grants, row policies"
python run_as.py 01_setup.sql
python run_as.py 02_policies.sql

echo "Done. IAM changes can take a few minutes; if the first impersonated query is refused, wait and retry."
