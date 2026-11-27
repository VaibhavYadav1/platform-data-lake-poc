# POC F: cost estimator vs actual BigQuery cost (24 to 26 November 2026)

**Project:** `gks-datalake-poc2-dev`, region `us-central1`. **Currency:** INR (billing currency), converted at **1 USD = 95.23 INR**, the rate in the billing export.
**Question:** does the BigQuery Future Cost Estimator (`scripts/cost_estimator`) agree with what Google actually billed for the days the POC ran?

## Result in one paragraph

The estimator's pricing and arithmetic are correct: given the real billed volume, it gives the same query cost as a hand calculation (INR 8.79), and with the free tier applied it predicts INR 0, which is what was billed. It over-estimates when it is given the raw query count, because it bills every query at a 10 MiB minimum: INR 19.17 against INR 8.79 for the same queries, about 2.2 times too high. The estimator was then extended with legacy streaming inserts and Storage Write API ingestion, the other two BigQuery billing lines that appeared. With all four lines and the real volumes it gives INR 8.8916, equal to the hand calculation (run D).

## What was compared

| | Source |
|---|---|
| **Actual billed** | Billing export `billing_export.gcp_billing_export_v1_014E34_84D3B1_696BF1`, service BigQuery |
| **Usage** | `INFORMATION_SCHEMA.JOBS_BY_PROJECT` (bytes billed, query count) and the export's usage lines |
| **List prices** | Cloud Billing Catalog API, SKUs for us-central1 (INR for the hand calculation, USD as the estimator retrieves them) |
| **Estimator** | `python scripts/cost_estimator/main.py estimate ...` with application default credentials (no API key) |

## Window and data limits

- **Window: 24, 25 and 26 November.** The billing export only starts on 24 November and is not back-filled.
- **No BigQuery row exists in the export for 24 November.** That day's usage (0.003643 TiB) is missing from billing, so "actual billed" really covers 25 and 26 November. Usage inputs use all three days from job history.
- On 26 November the export and job history agree exactly (0.008535 TiB). On 25 November they differ slightly (0.002384 against 0.002594 TiB), probably a day-boundary effect.
- The free tiers (1 TiB of queries and 10 GiB of storage per month) apply per billing account per month, so they decide the result for a three-day window.

## Inputs

| Day (UTC) | Queries | Bytes billed | TiB billed |
|---|---:|---:|---:|
| 24 Nov | 994 | 4,005,560,320 | 0.003643 |
| 25 Nov | 545 | 2,852,126,720 | 0.002594 |
| 26 Nov | 1,839 | 9,384,755,200 | 0.008535 |
| **Total** | **3,378** | **16,242,442,240 (15.13 GiB)** | **0.01477** |

- Storage: about 0.0004 GiB-months in total (a few MB), from the export's Active Logical Storage usage. `TABLE_STORAGE` could not be read (permission denied).
- Streaming inserts: 20.29 MiB, all on 26 November (the CRM loader's `load_log` writes).
- Average billed size per query: 4.59 MiB (16.24 GB divided by 3,378).

## Prices used

| Component | SKU | Catalog price (INR) | Same in USD | Free tier per month |
|---|---|---:|---:|---|
| Queries | Analysis (us-central1) | 595.19 per TiB | 6.25 | first 1 TiB |
| Active storage | Active Logical Storage (us-central1) | 2.19 per GiB-month | 0.023 | first 10 GiB |
| Streaming insert | Streaming Insert (us-central1) | 0.004761 per MiB | n/a | none |

## Results (INR)

| Scenario | Queries | Storage | Streaming | Total |
|---|---:|---:|---:|---:|
| **Actual billed** (gross, before credits) | 0 | 0 | 0.097 | **0.10** |
| **Actual billed** (net of credits) | 0 | 0 | 0 | **0** |
| Hand calculation, list price, no free tier, real billed volume | 8.79 | 0.001 | 0.097 | 8.89 |
| Hand calculation, free tier applied | 0 | 0 | 0.097 | 0.097 |
| **Estimator**, free tier applied (run A) | 0 | 0 | 0.097 | **0.097** |
| **Estimator**, list price, same queries as entered (3,378 x 4.59 MiB, run B) | 19.17 | 0.001 | not covered | 19.17 |
| **Estimator**, list price, volume matched to real billed bytes (1,549 queries x 10 MiB, run C) | 8.79 | 0.001 | not covered | 8.79 |
| **Estimator**, all four BigQuery lines, list price, real volumes (run D, 0.4025 MiB stored, 1,549 x 10 MiB queries, 20.29 MiB streamed, 0.000729 GiB Storage API) | 8.7924 | 0.0009 | 0.0966 (+ Storage API 0.0017) | **8.8916** |

USD figures from the estimator: run B queries 0.2013, run C queries 0.0923, storage 0.0000092.

## Every BigQuery billing line, 24 to 26 November (free tier ignored, list price)

The export has BigQuery usage under two services, **BigQuery** and **BigQuery Storage API**. Every line that appeared:

| Billing line (SKU) | Usage | List price | Hand calc (INR) | Actual billed (INR) | Estimator covers it? |
|---|---:|---|---:|---|---|
| Analysis (us-central1), on-demand queries | 0.014772 TiB | $6.25 per TiB | 8.7924 | 0 (free tier) | **Yes** |
| Active Logical Storage (us-central1) | 0.000393 GiB-month | $0.023 per GiB-month | 0.0009 | 0 (free tier) | **Yes** |
| Streaming Insert (us-central1) | 20.29 MiB | $0.00005 per MiB | 0.0966 | 0.0966 gross, cancelled by a promotion credit (FreeTrial) | **Yes** (`--streaming-size`) |
| BigQuery Storage API - Write (us-central1) | 0.000729 GiB | $0.025 per GiB (first 2 TiB free) | 0.0017 | 0 (free tier) | **Yes** (`--storage-api-size`) |
| **Total** | | | **8.8916** | **0.0966 gross, 0 net** | |

The estimator's total for the lines it covers (run C, volume matched to real billed bytes) is **INR 8.7932**. That equals the hand calculation for the same two lines (8.7924 + 0.0009 = 8.7932). With streaming inserts and Storage API writes added (run D) the estimator's total is INR 8.8916, equal to the full BigQuery list-price total, to the paisa, for every line.

**BigQuery billing lines that exist in the catalog but had no usage in this window** (all would be zero here): long-term logical storage ($0.016 per GiB-month), active and long-term physical storage ($0.04 and $0.02), Storage API read ($1.10 per TiB after 300 TiB free), BigQuery editions (Standard $0.04, Enterprise $0.06, Enterprise Plus $0.10 per slot-hour in us-central1; 1-year and 3-year commitments cheaper), legacy flat-rate, BI Engine ($0.0416 per GiB-hour), Data Transfer Service, network egress (inter-region, internet, intra-region at $0), notebook disk and AI token SKUs. Of these the estimator covers only physical or logical storage, Enterprise Edition and BI Engine, and only when asked.

## Findings

1. **Free tier:** the estimator applies it correctly (predicts 0, billed was 0 net). At this volume the free tier absorbs all query and storage cost, and a calculator that ignored it would overstate the bill by about 90 times (INR 8.89 against 0.10).
2. **Arithmetic and prices:** run C equals the hand calculation to the paisa (INR 8.79), and the USD rates the estimator retrieves match the INR catalog rates at 95.23. No defect found in pricing, tiers or unit conversion.
3. **The gap comes from the query count entered, not from the maths.** Of the 3,378 queries, only **1,136 were billed** (minimum 10 MiB each, average 13.64 MiB); **2,242 (66%) billed zero bytes**, mostly view and schema statements, metadata and some SELECTs (83 were cache hits). The estimator bills every query it is given at no less than 10 MiB, so entering all 3,378 gives 0.0322 TiB against 0.01477 TiB actually billed (2.2 times, INR 19.17 against 8.79). Entering the 1,136 billed queries instead gives INR 9.03, 2.7% above the hand calculation: the estimator rounds the average size (13.64 MiB) up to a whole 14 MiB per query, while the real bill rounds each query separately.
   - Storage differs by 1.2% between a plain GiB-month and the estimator because the catalog defines one GiB-month as 721 hours, not 730; the estimator is right and a hand calculation must use 730/721 = 1.0125.
4. **Streaming inserts and Storage API:** added to the estimator after the first comparison. Streaming was the only gross charge (INR 0.097) and the estimator now reproduces it. Dataplex, Cloud SQL, Cloud Build and Cloud Run were far larger lines on the bill (all offset by credits) and remain outside this estimator, which covers BigQuery storage, on-demand queries, streaming inserts, Storage Write API ingestion, Enterprise Edition and BI Engine.

## Limits of this comparison

- A three-day window at tiny volume (about 15 GiB queried, a few MB stored) cannot test the paid tiers: the free tier was never exhausted, so the real bill gives no check on the INR 595.19 per TiB rate beyond the catalog itself.
- Actual billing covers two of the three days (see above).
- Billed amounts are net of promotional credits; the gross figure is shown separately.

## Suggested follow-ups

1. Enter only the queries that bill (count the ones with `total_bytes_billed > 0` in `INFORMATION_SCHEMA.JOBS_BY_PROJECT`) when comparing the estimator with real usage, and say so in the estimator's README.
2. When benchmark volumes are larger (POC F benchmark days), repeat the comparison on a window that exceeds the free tier, so the paid rate is tested against real billing.
3. Done: streaming inserts and the Storage Write API are in the estimator. Still not covered: Storage API reads, Data Transfer Service and egress (no usage in this window).

## Reproduce

```
# actual (billing export), per day and SKU
SELECT DATE(usage_start_time) day, sku.description, SUM(usage.amount_in_pricing_units), SUM(cost_at_list), SUM(cost)
FROM `gks-datalake-poc2-dev.billing_export.gcp_billing_export_v1_014E34_84D3B1_696BF1`
WHERE service.description = 'BigQuery' AND DATE(usage_start_time) BETWEEN '2026-11-24' AND '2026-11-26' GROUP BY 1, 2

# estimator, run A (use application default credentials; do not put an API key in a command line or file)
set GCP_QUOTA_PROJECT=gks-datalake-poc2-dev
python scripts/cost_estimator/main.py estimate --storage-size 0.4025 --storage-unit MiB --queries-per-month 3378 --query-size 4.585554 --query-unit MiB
# run D adds:  --streaming-size 20.29 --streaming-unit MiB --storage-api-size 0.000729 --storage-api-unit GiB --storage-api-free-gib-used 2048
# run B adds:  --storage-free-gib-used 10 --on-demand-free-tib-used 1
# run C:       --queries-per-month 1549 --query-size 10 --query-unit MiB  (plus the run B flags)
```
