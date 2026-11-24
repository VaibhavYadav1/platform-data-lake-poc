# A6: case events, quick reference

**Owner:** Dev 4 · **Days:** 3–4 · **Needs:** 0.7 (Avro schema; `specs.md` not written yet: use the guide's 11.2
proposal and get Dev 5 to confirm) · **Done when:** a test message lands in `raw_lpos.case_event`.

Full steps: `A6_STEPS.md`. Design: POC A guide section 11.

## Checklist

- [ ] `terraform/shared/schemas/case_event.avsc`: the guide's 11.2 schema exactly (`g2_store_id`, `event_ts` in
      microseconds, nullable `offender_token`, `loss_amount`, `items_count`)
- [ ] `terraform/modules/pubsub_bq/`: `versions.tf`, `variables.tf`, `main.tf` (guide 11.3), `outputs.tf`
- [ ] `terraform/shared/case_events.tf`: `raw_lpos` dataset + module call
- [ ] `gcloud beta services identity create --service=pubsub.googleapis.com`
- [ ] `terraform plan`: 10 to add, 0 change, 0 destroy; Dev 2 reviews; apply
- [ ] Publish test-0001 (nulls) and test-0002 (wrapped nullable values); both land in `raw_lpos.case_event`
- [ ] A malformed message is refused at publish
- [ ] Record the JSON encoding in `specs.md`; update the POC A guide; commit to `main`

## Resources

| Resource | Name | Purpose |
| --- | --- | --- |
| Schema | `poc-case-event` | Avro, checked at publish |
| Topic | `poc-case-events` | JSON encoding, schema attached |
| Topic | `poc-case-events-dlq` | Dead letters after 5 tries |
| Subscription | `poc-case-events-to-bq` | BigQuery subscription, `use_topic_schema`, `write_metadata` |
| Subscription | `poc-case-events-dlq-sub` | Pull, to inspect dead letters |
| Dataset / table | `raw_lpos.case_event` | Partitioned by day on `publish_time`; Avro fields + `subscription_name`, `message_id`, `publish_time`, `attributes` |
| IAM (Pub/Sub service agent) | dataEditor on `raw_lpos`; publisher on the DLQ; subscriber on `to_bq` | Writing and dead-lettering |
| Later (A8) | publisher on `poc-case-events` for `sa-simulator` | The account doesn't exist yet |

## What it enables

A7 (publisher with ~2% duplicates and ~1% unknown stores), C10 (`stg_lpos__case_event` dedupe, `fct_case`),
AT-22/AT-23 (case-event latency and dead letters, G7), and the watchdog's case-event check (E7).
