# A6 Case Event Stream Infrastructure - Deployment Complete ✅

**Date:** 2026-11-26  
**Task:** A6 - Case Event Stream Infrastructure  
**Status:** ✅ ALL STEPS COMPLETE (Steps 1-6)

---

## Summary

Successfully deployed complete Pub/Sub → BigQuery pipeline for case events, including schema validation, dead-letter queue, and comprehensive testing. All 10 infrastructure resources created successfully. JSON encoding format confirmed through live testing.

---

## Steps Completed

### ✅ Step 1: Create Avro Schema File
- **File:** `terraform/shared/schemas/case_event.avsc`
- **Schema:** 9 fields (6 required, 3 nullable with union types)
- **Namespace:** poc.lpos
- **Critical:** Uses `timestamp-micros` for event_ts (16-digit microseconds, not 13-digit milliseconds)

### ✅ Step 2: Create pubsub_bq Module
- **Location:** `terraform/modules/pubsub_bq/`
- **Files:** 4 (versions.tf, variables.tf, main.tf, outputs.tf)
- **Resources:** 9 (schema, 2 topics, 1 table, 2 subscriptions, 3 IAM grants)
- **Features:**
  - Avro schema validation on publish
  - Dead-letter queue with max 5 retries
  - BigQuery write with metadata
  - Day partitioning by publish_time

### ✅ Step 3: Integration in shared/case_events.tf
- **Dataset:** raw_lpos (Phase 2 POC sandbox)
- **Module Call:** Wires schema file to module
- **Output:** case_topic_id exported for other modules

### ✅ Step 4: Deploy Infrastructure
- **Command:** `terraform init && terraform apply`
- **Resources Created:** 10 total
  1. `google_bigquery_dataset.raw_lpos` - Dataset
  2. `google_pubsub_schema.case_event` - Avro schema
  3. `google_pubsub_topic.case_events` - Main topic
  4. `google_pubsub_topic.dlq` - Dead letter topic
  5. `google_bigquery_table.case_event` - Target table
  6. `google_pubsub_subscription.to_bq` - Main subscription
  7. `google_pubsub_subscription.dlq_sub` - DLQ subscription
  8. `google_bigquery_dataset_iam_member.pubsub_writer` - IAM grant
  9. `google_pubsub_subscription_iam_member.main_subscriber` - IAM grant
  10. `google_pubsub_topic_iam_member.dlq_publisher` - IAM grant
- **Service Agent:** Automatically created (service-166366601382@gcp-sa-pubsub.iam.gserviceaccount.com)

### ✅ Step 5: Test Message Publishing
**Method:** Manual gcloud commands with 3 test messages

**Test 1 - All nulls (plain JSON null):**
```json
{
  "event_id": "evt-001",
  "case_id": "case-001",
  "event_type": "case_opened",
  "event_ts": 1704067200000000,
  "g2_store_id": "store-123",
  "case_status": "open",
  "offender_token": null,
  "loss_amount": null,
  "items_count": null
}
```
✅ **Result:** SUCCESS - Message ID 23545660590136389, landed in BigQuery

**Test 2 - Missing optional fields:**
```json
{
  "event_id": "evt-005",
  "case_id": "case-005",
  ...
  // offender_token, loss_amount, items_count omitted
}
```
❌ **Result:** REJECTED - "Field was not found in JSON object: offender_token"

**Test 3 - Plain (unwrapped) non-null values:**
```json
{
  ...
  "offender_token": "off-999",  // Plain string, not wrapped
  "loss_amount": 149.99,        // Plain number, not wrapped
  "items_count": 7              // Plain number, not wrapped
}
```
❌ **Result:** REJECTED - "JSON object with type string does not match schema which expected object"

**Test 4 - Wrapped format (CORRECT):**
```json
{
  "event_id": "evt-008",
  "case_id": "case-008",
  "event_type": "case_resolved",
  "event_ts": 1704672000000000,
  "g2_store_id": "store-444",
  "case_status": "closed",
  "offender_token": {"string": "off-888"},
  "loss_amount": {"double": 199.99},
  "items_count": {"int": 10}
}
```
✅ **Result:** SUCCESS - Message ID 23546709082655261, landed in BigQuery with all values

**BigQuery Verification:**
```
evt-001: offender_token=null, loss_amount=null, items_count=null
evt-006: offender_token=null, loss_amount=null, items_count=null  
evt-008: offender_token="off-888", loss_amount="199.99", items_count="10"
```

### ✅ Step 6: Document Encoding in specs.md
- **Updated:** `docs/poc2/specs.md` - Task 0.7 section
- **Result:** WRAPPED format required for union types
- **Added:** Complete encoding rules with examples and test results
- **Updated:** Implementation status checklist

---

## Key Findings

### JSON Encoding Format: WRAPPED (Avro Union Standard)

**Critical Rules for A7 Publisher:**

1. **ALL fields must be present**, even nullable ones with defaults
2. **Non-null union values must be wrapped**: `{"type": value}`
   - `{"string": "tok-123"}` for nullable strings
   - `{"double": 123.45}` for nullable doubles
   - `{"int": 42}` for nullable ints
3. **Null values use plain JSON null**: `"fieldName": null`
4. **Missing fields = validation failure**, even with Avro defaults

**Why This Matters:**
- Google Pub/Sub schema validation is strict
- Avro union types require explicit type specification in JSON
- Plain JSON (unwrapped) format fails validation
- This is standard Avro JSON encoding behavior

---

## Infrastructure Details

### Resources Created

**Dataset:**
```
Project: gks-datalake-poc2-dev
Dataset: raw_lpos
Description: Case events from Pub/Sub (A6): one row per message, duplicates included
Labels: poc=phase2, owner=dev4, managed_by=terraform
```

**Topics:**
```
Main: projects/gks-datalake-poc2-dev/topics/poc-case-events
  - Schema: projects/gks-datalake-poc2-dev/schemas/poc-case-event
  - Encoding: JSON
  - Validation: Enforced on publish

DLQ: projects/gks-datalake-poc2-dev/topics/poc-case-events-dlq
```

**Subscriptions:**
```
Main: poc-case-events-to-bq
  - Type: BigQuery subscription
  - Target: gks-datalake-poc2-dev.raw_lpos.case_event
  - Schema: Use topic schema
  - Metadata: Write publish_time, message_id, attributes
  - DLQ: Max 5 delivery attempts

DLQ: poc-case-events-dlq-sub
  - Type: Pull subscription
  - For manual inspection of failed messages
```

**BigQuery Table:**
```
Table: gks-datalake-poc2-dev.raw_lpos.case_event
Schema: 9 data fields + 4 metadata fields
  - event_id (STRING, REQUIRED)
  - case_id (STRING, REQUIRED)
  - event_type (STRING, REQUIRED)
  - event_ts (TIMESTAMP, REQUIRED)
  - g2_store_id (STRING, REQUIRED)
  - offender_token (STRING, NULLABLE)
  - case_status (STRING, REQUIRED)
  - loss_amount (FLOAT64, NULLABLE)
  - items_count (INT64, NULLABLE)
  - subscription_name (STRING, NULLABLE) - metadata
  - message_id (STRING, NULLABLE) - metadata
  - publish_time (TIMESTAMP, NULLABLE) - metadata
  - attributes (JSON, NULLABLE) - metadata

Partitioning: DAY by publish_time
Deletion Protection: false (POC environment)
```

---

## Next Steps

### A7: Publisher Code (simulator/case_events.py)

**Implementation Requirements:**
1. Use **wrapped format** for all nullable fields with non-null values
2. Always include ALL 9 fields in JSON payload
3. Convert timestamps to microseconds (multiply ms by 1000)
4. Use Python Pub/Sub client with JSON encoding

**Example Publisher Code:**
```python
import json
from google.cloud import pubsub_v1

def publish_case_event(event_data):
    """Publish case event with proper union wrapping"""
    message = {
        "event_id": event_data["event_id"],
        "case_id": event_data["case_id"],
        "event_type": event_data["event_type"],
        "event_ts": int(event_data["event_ts_ms"] * 1000),  # ms → μs
        "g2_store_id": event_data["g2_store_id"],
        "case_status": event_data["case_status"],
        # Wrap nullable fields if not None
        "offender_token": {"string": event_data["offender_token"]} if event_data.get("offender_token") else None,
        "loss_amount": {"double": event_data["loss_amount"]} if event_data.get("loss_amount") else None,
        "items_count": {"int": event_data["items_count"]} if event_data.get("items_count") else None,
    }
    
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(project_id, "poc-case-events")
    data = json.dumps(message).encode("utf-8")
    future = publisher.publish(topic_path, data)
    return future.result()  # message_id
```

### A8: Cloud Deployment

**After A7 Complete:**
1. Update `terraform/shared/simulator.tf` to add case_events publisher permissions
2. Add Cloud Build config for simulator Docker image
3. Deploy simulator to Cloud Run
4. Grant `sa-simulator` publisher role on `poc-case-events` topic
5. Add monitoring alert for case event freshness

---

## Files Changed

**New Files:**
- `terraform/shared/schemas/case_event.avsc` (Avro schema)
- `terraform/modules/pubsub_bq/versions.tf`
- `terraform/modules/pubsub_bq/variables.tf`
- `terraform/modules/pubsub_bq/main.tf` (9 resources)
- `terraform/modules/pubsub_bq/outputs.tf`
- `terraform/shared/case_events.tf` (integration)

**Updated Files:**
- `docs/poc2/specs.md` (documented JSON encoding result)

**All files committed:** Commit d2ecdc5 on main branch

---

## References

- **Task Spec:** docs/poc2/tasks.md (Task 0.7)
- **Implementation Guide:** A6_STEPS.md
- **Schema Spec:** docs/poc2/specs.md (Task 0.7 section)
- **Module Design:** Based on G2 path `datastream_bq` module pattern
- **Avro JSON Encoding:** https://avro.apache.org/docs/current/specification/#json-encoding

---

## Verification Commands

```powershell
# List topics
gcloud pubsub topics list --project=gks-datalake-poc2-dev --filter="name:case-events"

# List subscriptions
gcloud pubsub subscriptions list --project=gks-datalake-poc2-dev --filter="name:case-events"

# Check BigQuery dataset
bq ls --project_id=gks-datalake-poc2-dev | Select-String "raw_lpos"

# Check BigQuery table
bq ls --project_id=gks-datalake-poc2-dev raw_lpos

# Query messages
bq query --project_id=gks-datalake-poc2-dev --use_legacy_sql=false \
  "SELECT event_id, case_id, event_type, publish_time FROM raw_lpos.case_event ORDER BY publish_time DESC LIMIT 10"

# Publish test message
gcloud pubsub topics publish poc-case-events --project=gks-datalake-poc2-dev \
  --message='{"event_id":"test-001","case_id":"case-test","event_type":"CASE_OPENED","event_ts":1704067200000000,"g2_store_id":"S001","case_status":"OPEN","offender_token":null,"loss_amount":null,"items_count":null}'
```

---

## Success Criteria ✅

- [x] All 10 infrastructure resources deployed successfully
- [x] Avro schema registered and validated
- [x] Test messages published successfully
- [x] Messages landed in BigQuery with correct schema
- [x] JSON encoding format determined (WRAPPED)
- [x] Encoding documented in specs.md
- [x] Ready for A7 publisher implementation

**A6 COMPLETE** - Ready to proceed with A7 publisher code
