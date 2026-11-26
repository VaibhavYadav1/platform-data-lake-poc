# A7 Case Event Publisher - Quick Reference

## ✅ Status: COMPLETE (Commit bff3705)

---

## Quick Commands

### Publish Test Events
```bash
python -m simulator case-events \
  --topic projects/gks-datalake-poc2-dev/topics/poc-case-events \
  --count 10 \
  --seed 42
```

### Verify in BigQuery
```bash
bq query --project_id=gks-datalake-poc2-dev --use_legacy_sql=false \
  "SELECT event_id, case_id, event_type, g2_store_id, publish_time 
   FROM raw_lpos.case_event 
   ORDER BY publish_time DESC 
   LIMIT 10"
```

### Run Continuous Mode
```bash
export CASE_TOPIC=projects/gks-datalake-poc2-dev/topics/poc-case-events
export G2_DATABASE_URL=postgresql://...
python -m simulator tick
```

---

## Message Format (Critical!)

### ✅ CORRECT - Wrapped Format
```json
{
  "event_id": "evt-13018f13c489",
  "case_id": "case-8eb0dce0",
  "event_type": "CASE_CLOSED",
  "event_ts": 1732638286000000,
  "g2_store_id": "S015",
  "case_status": "CLOSED",
  "offender_token": {"string": "off-a1b2c3d4"},
  "loss_amount": {"double": 123.45},
  "items_count": {"int": 7}
}
```

### ❌ WRONG - Plain Format
```json
{
  "offender_token": "off-a1b2c3d4",  // ❌ Not wrapped!
  "loss_amount": 123.45,              // ❌ Not wrapped!
  "items_count": 7                    // ❌ Not wrapped!
}
```

---

## Key Rules

1. **ALL 9 fields must be present** (even nullable ones)
2. **Non-null union values MUST be wrapped**: `{"type": value}`
3. **Null values use plain JSON null**: `null`
4. **Timestamps in MICROSECONDS**: multiply ms by 1000
5. **Never use probe store S999**

---

## Data Generated

- **Event Types**: CASE_OPENED (33%), CASE_UPDATED (33%), CASE_CLOSED (33%)
- **Stores**: S001-S040 (baseline range), ~1% S990 (unknown)
- **Duplicates**: ~2% (same event_id, different message_id)
- **Optional Fields**:
  - offender_token: 30% populated
  - loss_amount: 40% populated  
  - items_count: 50% populated

---

## Files

- **Implementation**: `simulator/case_events.py` (219 lines)
- **CLI**: `simulator/cli.py` (added case-events & tick commands)
- **Requirements**: `simulator/requirements-runtime.txt` (added google-cloud-pubsub)
- **Schema**: `terraform/shared/schemas/case_event.avsc`
- **Docs**: `A7_PUBLISHER_COMPLETE.md`, `A7_SUMMARY.md`

---

## Testing Done

- ✅ 163 messages published (3 batches)
- ✅ All landed in BigQuery
- ✅ Schema validation passed
- ✅ Union wrapping correct
- ✅ Duplicates working (~3% rate)
- ✅ Optional fields working

---

## Next: A8

1. Add IAM: `roles/pubsub.publisher` for `sa-simulator`
2. Build Docker image with runtime deps
3. Deploy to Cloud Run with Cloud Scheduler
4. Add monitoring for case event freshness

---

## Troubleshooting

**Import Error?** → `pip install google-cloud-pubsub`  
**Auth Error?** → `gcloud auth application-default login`  
**Schema Error?** → Check ALL fields present and unions wrapped  
**No Data?** → Wait 10-15 seconds for Pub/Sub → BigQuery delay

---

**Ready for A8 Cloud Deployment!** 🚀
