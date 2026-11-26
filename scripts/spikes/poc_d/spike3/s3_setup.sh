#!/usr/bin/env bash
# Spike 3 set-up: is BigQuery data masking available to us with on-demand pricing?
# Creates a policy-tag taxonomy and tag, a table with tagged contact columns, and a SHA-256 masking data policy.
# Run as yourself, from the poc_d folder:  bash spike3/s3_setup.sh
# THE ANSWER TO SPIKE 3 is mostly step 4: if creating the data policy fails, copy the exact error into spikes.md.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source spike.env; set +a
STATE=spike3/.state    # remembers the taxonomy, tag and data policy names for the tests and teardown
API=https://bigquerydatapolicy.googleapis.com/v1
TOKEN=$(gcloud auth print-access-token)

echo "== 1. Taxonomy and policy tag (fine-grained access control on)"
# Through the Data Catalog REST API: gcloud 500+ no longer has "data-catalog taxonomies create".
DC=https://datacatalog.googleapis.com/v1
name_of() { python -c "import json,sys; d=json.load(sys.stdin); print(d.get('name') or sys.exit(json.dumps(d)))"; }
TAXONOMY=$(curl -sS -X POST "$DC/projects/$PROJECT/locations/$LOCATION/taxonomies"   -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"   -d "{\"displayName\": \"spike-pii-$(date +%H%M%S)\", \"activatedPolicyTypes\": [\"FINE_GRAINED_ACCESS_CONTROL\"]}" | name_of)
TAG=$(curl -sS -X POST "$DC/$TAXONOMY/policyTags"   -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"   -d '{"displayName": "pii_direct"}' | name_of)
echo "TAXONOMY=$TAXONOMY" > "$STATE"
echo "TAG=$TAG" >> "$STATE"
echo "   taxonomy $TAXONOMY"
echo "   tag      $TAG"

echo "== 2. You get fine-grained reader (to see real values and insert test rows); nobody else does"
curl -sS -X POST "$DC/$TAG:setIamPolicy"   -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"   -d "{\"policy\": {\"bindings\": [{\"role\": \"roles/datacatalog.categoryFineGrainedReader\", \"members\": [\"user:$ME\"]}]}}" >/dev/null

echo "== 3. Table spike_rls.account_contact with both contact columns tagged"
SCHEMA=$(mktemp)
cat > "$SCHEMA" <<JSON
[
  {"name": "account_id", "type": "STRING"},
  {"name": "primary_contact_name", "type": "STRING", "policyTags": {"names": ["$TAG"]}},
  {"name": "primary_contact_email", "type": "STRING", "policyTags": {"names": ["$TAG"]}}
]
JSON
bq --project_id "$PROJECT" rm -f -t "$PROJECT:spike_rls.account_contact" >/dev/null 2>&1 || true
bq --project_id "$PROJECT" mk --table --expiration 259200 "$PROJECT:spike_rls.account_contact" "$SCHEMA"
rm -f "$SCHEMA"
python run_as.py spike3/s3_insert_rows.sql

echo "== 4. Masking data policy (SHA-256) on the tag  <-- the spike's main question"
POLICY_ID=spike_pii_sha256_$(date +%H%M%S)
RESPONSE=$(curl -sS -X POST "$API/projects/$PROJECT/locations/$LOCATION/dataPolicies" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"dataPolicyId\": \"$POLICY_ID\", \"dataPolicyType\": \"DATA_MASKING_POLICY\",
       \"policyTag\": \"$TAG\", \"dataMaskingPolicy\": {\"predefinedExpression\": \"SHA256\"}}")
echo "$RESPONSE"
if echo "$RESPONSE" | grep -q '"error"'; then
  echo "!! Data policy NOT created. Spike 3 answer is probably 'no': record the error above in spikes.md."
  echo "   Continue with s3c and s3d anyway: they show the 'denied without the tag' behaviour D9 then relies on."
  exit 0
fi
POLICY="projects/$PROJECT/locations/$LOCATION/dataPolicies/$POLICY_ID"
echo "POLICY=$POLICY" >> "$STATE"

echo "== 5. Masked reader for spike-masked only"
curl -sS -X POST "$API/$POLICY:setIamPolicy" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"policy\": {\"bindings\": [{\"role\": \"roles/bigquerydatapolicy.maskedReader\",
       \"members\": [\"serviceAccount:$SA_MASKED\"]}]}}"
echo
echo "Done. Run the s3 tests (see README). Masked-reader grants can take a few minutes to apply."
