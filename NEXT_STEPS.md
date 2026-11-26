# Next Steps After A6 Completion

**Current Status:** ✅ A6 Complete (Infrastructure deployed and tested)  
**Latest Commit:** 85f590b on main  
**Date:** 2026-11-26

---

## What Just Happened

A6 (Case Event Stream Infrastructure) is **fully complete**:

1. ✅ Avro schema created and deployed
2. ✅ Pub/Sub topics and subscriptions created
3. ✅ BigQuery dataset and table created
4. ✅ All IAM permissions configured
5. ✅ Manual testing completed
6. ✅ JSON encoding format confirmed: **WRAPPED**
7. ✅ Documentation updated in specs.md

**10 Resources Deployed:**
- raw_lpos dataset
- case_event BigQuery table
- poc-case-event Avro schema
- poc-case-events topic
- poc-case-events-dlq topic
- poc-case-events-to-bq subscription
- poc-case-events-dlq-sub subscription
- 3 IAM grants

---

## Critical Finding: JSON Encoding Format

Google Pub/Sub with Avro schema validation requires **WRAPPED format** for union (nullable) types:

**CORRECT Format for A7:**
```json
{
  "event_id": "evt-001",
  "case_id": "case-001",
  "event_type": "CASE_OPENED",
  "event_ts": 1704067200000000,
  "g2_store_id": "store-123",
  "case_status": "OPEN",
  "offender_token": {"string": "tok-abc"},  // ← Wrapped!
  "loss_amount": {"double": 240.5},         // ← Wrapped!
  "items_count": {"int": 3}                 // ← Wrapped!
}
```

**For null values:**
```json
{
  "offender_token": null,  // ← Plain null, not wrapped
  "loss_amount": null,
  "items_count": null
}
```

**Rules:**
1. ALL 9 fields must be present (even nullable ones)
2. Non-null union values must be wrapped: `{"type": value}`
3. Null values use plain JSON null
4. Missing fields cause validation failure

---

## What to Do Next

### Option 1: Start A7 (Publisher Code) - RECOMMENDED

**Task:** Write Python publisher in `simulator/case_events.py`

**What you need:**
- Reference: `simulator/g2_events.py` (existing G2 publisher)
- Schema: `terraform/shared/schemas/case_event.avsc`
- Encoding rules: `docs/poc2/specs.md` (Task 0.7 → JSON Encoding section)
- Topic name: `poc-case-events`

**Key implementation points:**
```python
# In simulator/case_events.py
def build_case_event_message(event_data):
    """Build properly wrapped message for Pub/Sub"""
    message = {
        "event_id": event_data["event_id"],
        "case_id": event_data["case_id"],
        "event_type": event_data["event_type"],
        "event_ts": int(event_data["event_ts_ms"] * 1000),  # ms → μs!
        "g2_store_id": event_data["g2_store_id"],
        "case_status": event_data["case_status"],
        # Wrap non-null values
        "offender_token": {"string": event_data["offender_token"]} if event_data.get("offender_token") else None,
        "loss_amount": {"double": event_data["loss_amount"]} if event_data.get("loss_amount") else None,
        "items_count": {"int": event_data["items_count"]} if event_data.get("items_count") else None,
    }
    return message
```

**Testing locally:**
```powershell
# Run simulator with case events enabled
cd simulator
python main.py --case-events-only --dry-run  # Test without publishing
python main.py --case-events-only            # Publish to real topic
```

**Verification:**
```powershell
# Check messages landed in BigQuery
bq query --project_id=gks-datalake-poc2-dev --use_legacy_sql=false \
  "SELECT event_id, case_id, event_type, publish_time 
   FROM raw_lpos.case_event 
   ORDER BY publish_time DESC 
   LIMIT 10"
```

---

### Option 2: Continue with Other Tasks

If you want to work on something else before A7:

**Task B1:** CRM Export Specifications (Dev 5's task)  
**Task 0.8:** Other schema specifications  
**Review:** Code review for other team members  

---

## Service Account Question Answered

**Q:** "Why isn't sa-simulator created yet?"

**A:** Service account `sa-simulator` is created in **A8 (Cloud Deployment)**, not A6.

**Timeline:**
- **A6 (now):** Infrastructure created, manual testing with YOUR credentials
- **A7 (next):** Publisher code, local testing with YOUR credentials  
- **A8 (later):** Deploy to Cloud Run, create sa-simulator, grant permissions

**For local testing (A7):**
```powershell
# Use your own credentials
gcloud auth application-default login

# Run simulator locally
cd simulator
python main.py --case-events-only
```

**Location in code:**
```hcl
# terraform/shared/simulator.tf, lines 36-42
resource "google_service_account" "simulator" {
  project      = var.project_id
  account_id   = "sa-simulator"
  display_name = "Simulator (G2 and LPOS stand-ins) in Cloud Run"
}
```

---

## Task Order Confirmed

✅ **Recommended order:**
1. ~~A6: Infrastructure (DONE)~~
2. **A7: Publisher code (NEXT)** ← You are here
3. A8: Cloud deployment (creates sa-simulator)

**Why this order:**
- A7 needs the infrastructure from A6 (topics, schema) ✓
- A7 needs the encoding format from A6 Step 5 ✓
- A8 needs working publisher code from A7 to deploy
- Local testing (A7) uses your credentials, not sa-simulator

---

## Files to Reference

**For A7 implementation:**
```
📁 simulator/
  ├── g2_events.py          ← Existing G2 publisher (reference pattern)
  ├── case_events.py        ← Create this for case events
  └── main.py               ← Add case events CLI flags

📁 terraform/shared/schemas/
  └── case_event.avsc       ← Your schema (9 fields)

📁 docs/poc2/
  └── specs.md              ← Encoding rules (Task 0.7 section)

📁 docs/
  └── A6_STEPS.md           ← Step 7 onwards (A7 and A8)
```

---

## Quick Commands

**Check infrastructure:**
```powershell
# Topics
gcloud pubsub topics list --project=gks-datalake-poc2-dev --filter="name:case-events"

# Subscriptions  
gcloud pubsub subscriptions list --project=gks-datalake-poc2-dev --filter="name:case-events"

# BigQuery
bq ls --project_id=gks-datalake-poc2-dev raw_lpos
```

**Publish test message:**
```powershell
gcloud pubsub topics publish poc-case-events `
  --project=gks-datalake-poc2-dev `
  --message='{"event_id":"manual-test-001","case_id":"case-999","event_type":"CASE_OPENED","event_ts":1704067200000000,"g2_store_id":"S001","case_status":"OPEN","offender_token":null,"loss_amount":null,"items_count":null}'
```

**Query messages:**
```powershell
bq query --project_id=gks-datalake-poc2-dev --use_legacy_sql=false `
  "SELECT * FROM raw_lpos.case_event ORDER BY publish_time DESC LIMIT 5"
```

---

## Summary

**You have successfully:**
- ✅ Completed Task 0.7 (schema specification)
- ✅ Completed A6 Steps 1-6 (infrastructure deployment and testing)
- ✅ Determined JSON encoding format (WRAPPED)
- ✅ Updated documentation
- ✅ Committed and pushed to main (commit 85f590b)

**You are ready to:**
- ✅ Start A7 publisher implementation
- ✅ Test locally with your credentials
- ✅ Verify messages flow through the pipeline

**You understand:**
- ✅ Why sa-simulator doesn't exist yet (created in A8)
- ✅ Correct task order (A6 → A7 → A8)
- ✅ Wrapped JSON format requirements

---

## Questions?

If you need help with A7:
1. Check `simulator/g2_events.py` for reference pattern
2. Check `docs/poc2/specs.md` for encoding rules
3. Check `A6_DEPLOYMENT_COMPLETE.md` for detailed examples

**Next command to run:**
```powershell
# Create the publisher file
code simulator/case_events.py
```

Good luck with A7! 🚀
