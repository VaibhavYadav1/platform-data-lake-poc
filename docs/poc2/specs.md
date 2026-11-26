# Specs

**Owner:** Dev 5  
**Tasks:** 0.7, B1  
**Last Updated:** [Current Date] - Task 0.7 completed

---

## Task 0.7: Case Event Avro Schema ✅

**Status:** CONFIRMED (derived from main branch dbt models @ d5fbcaa)  
**Confirmed by:** Analysis of `stg_lpos__case_event` and `fct_case` models

### Avro Schema: `case_event.avsc`

```json
{
  "type": "record",
  "name": "CaseEvent",
  "namespace": "poc.lpos",
  "doc": "Case lifecycle event from LPOS simulator",
  "fields": [
    {
      "name": "event_id",
      "type": "string",
      "doc": "Unique event identifier (primary key for deduplication)"
    },
    {
      "name": "case_id",
      "type": "string",
      "doc": "Case identifier (multiple events per case)"
    },
    {
      "name": "event_type",
      "type": "string",
      "doc": "CASE_OPENED, CASE_UPDATED, or CASE_CLOSED"
    },
    {
      "name": "event_ts",
      "type": {
        "type": "long",
        "logicalType": "timestamp-micros"
      },
      "doc": "Event timestamp in MICROSECONDS (not milliseconds)"
    },
    {
      "name": "g2_store_id",
      "type": "string",
      "doc": "Store ID from G2 (validated in staging, DQ44)"
    },
    {
      "name": "offender_token",
      "type": ["null", "string"],
      "default": null,
      "doc": "Opaque offender identifier (personal data)"
    },
    {
      "name": "case_status",
      "type": "string",
      "doc": "OPEN, UNDER_REVIEW, or CLOSED"
    },
    {
      "name": "loss_amount",
      "type": ["null", "double"],
      "default": null,
      "doc": "Monetary loss amount (nullable)"
    },
    {
      "name": "items_count",
      "type": ["null", "int"],
      "default": null,
      "doc": "Number of items involved (nullable)"
    }
  ]
}
```

### Field Specifications

**Required Fields:**

- `event_id` (string): Unique event identifier - primary key
- `case_id` (string): Case identifier - business key
- `event_type` (string): CASE_OPENED | CASE_UPDATED | CASE_CLOSED
- `event_ts` (timestamp-micros): Event timestamp in **MICROSECONDS**
- `g2_store_id` (string): Store ID from G2 system
- `case_status` (string): OPEN | UNDER_REVIEW | CLOSED

**Nullable Fields:**

- `offender_token` (string?): Opaque offender identifier (PII)
- `loss_amount` (double?): Monetary loss amount
- `items_count` (int?): Number of items involved

### Critical Notes

1. **Timestamp Format:** `event_ts` uses `timestamp-micros` (MICROSECONDS, not milliseconds)
   - Correct: `1794996003000000` (μs)
   - Wrong: `1794996003000` (ms → year 1970)

2. **Store ID Field:** Uses `g2_store_id` (not `store_id`) for clarity
   - Validated against `stg_g2__stores` in staging
   - Unknown stores flagged with DQ44

3. **Personal Data:** `offender_token` is PII
   - Must be opaque (never actual names)
   - Requires anonymization for external sharing

### JSON Encoding for Nullable Fields

**Testing Required:** During A6 implementation, test both formats:

**Wrapped Format (Avro standard):**

```json
{
  "offender_token": { "string": "tok-abc" },
  "loss_amount": { "double": 240.5 },
  "items_count": { "int": 3 }
}
```

**Plain Format:**

```json
{
  "offender_token": "tok-abc",
  "loss_amount": 240.5,
  "items_count": 3
}
```

**Result:** [TO BE FILLED IN A6 STEP 5] - Use ****\_**** format in A7 publisher

### Data Quality Rules

**DQ35: Duplicate Detection**

- ~2% of events published twice (same `event_id`, different `message_id`)
- Detected in staging: `count(*) over (partition by event_id) as copies_received`
- Deduplication: Keep first by `publish_time, message_id`

**DQ44: Unknown Store Validation**

- ~1% of events with invalid `g2_store_id` (not in `stg_g2__stores`)
- Never use probe store S999 for defects
- Flagged in staging: `is_unknown_store = true`
- Cases at unknown stores: `tenant_id = null`, `_dq_status = 'WARN'`

### Usage in dbt Models

**Source:** `raw_lpos.case_event`

- Dataset: `raw_lpos` (created by A6)
- Table: `case_event` (partitioned by `publish_time`)
- Loaded at: `publish_time`
- Freshness: warn 5min, error 30min

**Staging:** `stg_lpos__case_event`

- Input: `raw_lpos.case_event` (with duplicates)
- Output: 1 row per `event_id` (deduplicated)
- Validation: `is_unknown_store` flag (DQ44)
- Tests: unique `event_id`, not null, accepted event_types

**Facts:** `fct_case`

- Input: `stg_lpos__case_event`
- Output: 1 row per `case_id` (latest state)
- Incremental: merge on `case_id`
- Partitioned by: `case_date`

### Implementation Status

- [x] Schema confirmed from main branch dbt models
- [x] Documented in specs.md (Task 0.7)
- [ ] Avro schema file created (A6 Step 1)
- [ ] JSON encoding tested (A6 Step 5)
- [ ] Publisher implemented with confirmed encoding (A7)

---

## Task B1: CRM Export Specifications

_To be written._ Customer type codes, CRM export format, field mappings.

---

## Appendix: Other Specifications

_To be written._

- Tenant model
- Appendix A mapping
- Personal-data inventory
- Store-health rules
- Golden scenarios
