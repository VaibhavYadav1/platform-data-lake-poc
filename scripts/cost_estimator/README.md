# scripts/cost_estimator

**BigQuery Future Cost Estimator (POC F).** You state the BigQuery usage you expect; it prices that usage with current public list prices
from the Cloud Billing Catalog API and reports an **Estimated Future Cost**, monthly and annual.

It does **not** read existing jobs, usage or billing, and it never reports an actual or historical cost. It creates, changes and
deletes nothing in Google Cloud.

Covered: BigQuery storage, on-demand query processing, legacy streaming inserts (optional), Storage Write API ingestion (optional), Enterprise Edition (optional) and BI Engine (optional). Nothing else.

## Run it

```
pip install -r scripts/cost_estimator/requirements.txt

# storage and queries from flags
python scripts/cost_estimator/main.py estimate --storage-size 5 --storage-unit TiB \
    --queries-per-day 200 --operating-days 22 --query-size 50 --query-unit GiB

# everything from a file, flags override it; optional components turned on
python scripts/cost_estimator/main.py estimate --config scripts/cost_estimator/example_usage.json \
    --enterprise --enterprise-mode autoscale --enterprise-slots 100 --enterprise-hours-per-day 8 --enterprise-days-per-month 22 \
    --bi-engine --bi-capacity 10 --bi-unit GiB --bi-hours-per-day 8 --bi-days-per-month 22 --out-dir cost_report

python scripts/cost_estimator/main.py prices --region us-central1     # the rates the API returns
python -m pytest scripts/cost_estimator/tests
```

The report goes to the screen (Markdown, or `--format json`); `--out-dir` also writes `estimate.md` and `estimate.json` (git ignores `cost_report/`).
Invalid inputs and API problems print `error: ...` and exit with code 2.

### Credentials: environment variables only

| Variable | Use |
|---|---|
| `GCP_BILLING_API_KEY` | an API key for the Cloud Billing API. Sent in the `x-goog-api-key` header, never in a URL, and redacted from every error message |
| `GCP_QUOTA_PROJECT` | with Application Default Credentials only: the project billed for API calls |

Without a key it uses Application Default Credentials (`gcloud auth application-default login`). Public prices need no IAM role.

## Inputs

All inputs are your assumptions. Give them as flags or in a JSON file (`example_usage.json`); flags win. A component that is not given, or
has `"enabled": false`, is not estimated. At least one component is required. Unknown fields are rejected, so a typo cannot silently change a result.

| Component | Input | Default | Rule |
|---|---|---|---|
| all | `region` | `us-central1` | prices are filtered to this region; `us` and `eu` select the multi-regions |
| Storage | `size` + `unit` | **unit required** | not negative |
| | `duration_months` | 1 | greater than 0 |
| | `billing_model` | `logical` | `logical` or `physical`; the size is the bytes that model bills |
| | `free_gib_already_used` | 0 | free storage other usage on the billing account already used this month |
| On-demand | `per_day` + `operating_days`, **or** `per_month` | days: 30 | exactly one of per_day / per_month; days 1 to 31 |
| | `avg_data_per_query` + `unit` | **unit required** | not negative |
| | `tables_per_query` | 1 | whole number, 1 or more; the 10 MiB billing minimum applies per referenced table |
| | `free_tib_already_used` | 0 | free query TiB already used this month elsewhere on the account |
| Enterprise | `slots` | required | greater than 0 |
| | `mode` | `baseline` | `baseline` or `autoscale` |
| | `hours_per_day`, `days_per_month` | required | hours 0 to 24, days 0 to 31 |
| Streaming (`streaming`) | `size_per_month` + `unit` | **unit required** | data streamed per month through `insertAll`; no free tier |
| Storage API (`storage_api`) | `size_per_month` + `unit` | **unit required** | data written per month; first 2 TiB a month free |
| | `free_gib_already_used` | 0 | free GiB already used this month elsewhere on the account |
| | `autoscale_utilization` | 1.0 | autoscale only: share of operating time slots are scaled up, 0 to 1 |
| BI Engine | `capacity` + `unit` | **unit required** | greater than 0 (a range outside 1 to 250 GiB gets a warning) |
| | `hours_per_day`, `days_per_month` | required | hours 0 to 24, days 0 to 31 |

**Units are required** wherever a size is given: `GB` and `GiB` differ by 7%, so a missing unit is an error, not a silent default. `KB MB GB TB PB` are decimal (powers of 1000). `KiB MiB GiB TiB PiB` are binary (powers of 1024). BigQuery bills in GiB and TiB, so
`1 TB` is `0.909 TiB`; use `GiB` or `TiB` to avoid the conversion. Units are converted before any price is applied.

**Operating days** for `per_day` default to 30 when omitted, and the report says so.

## Prices

Retrieved from `GET https://cloudbilling.googleapis.com/v1/services/{id}/skus` for the three services:

| Service | ID | Used for |
|---|---|---|
| BigQuery | `24E6-581D-38E5` | storage, on-demand analysis |
| BigQuery Reservation API | `16B8-3DDA-9F10` | Enterprise Edition slot-hours |
| BigQuery BI Engine | `650B-3C82-34DB` | BI Engine GiB-hours |
| BigQuery Storage API | `DCC9-8DB9-673F` | Storage Write API ingestion (GiB) |

Streaming inserts are in the BigQuery service (`24E6-581D-38E5`), resource group `Streaming`.

- Only the services a requested component needs are fetched, so a missing Enterprise or BI Engine price cannot break a storage estimate.
- SKUs are chosen by rule (service, region, resource group, description), never by ID. A rule that finds none or several raises an error that names the
  region and lists the regions that are priced; it does not guess. Pay-as-you-go Enterprise is chosen, not the 1/3-year commitment or Enterprise Plus SKUs.
- The unit and its base-unit conversion come from the API; if the catalog changes a billing unit the estimate stops with an error instead of mispricing.
- Tiers and free tiers come from `tieredRates`. The catalog marks storage and on-demand analysis `ACCOUNT / MONTHLY`: the free 10 GiB (per storage SKU) and the free TiB belong to the
  billing account and reset each month. (The billing docs describe the free query tier as per project; with one project and nothing else on the account both agree.)
- Multi-regions are matched by the names the catalog uses, which differ by service (the EU multi-region is `eu` for Editions, `europe` for BI Engine, and storage and queries share a SKU listed as `us`, `europe`). Of the 58 locations the catalog prices for queries, 38 have all four components (the others are mostly BI Engine, which is priced in fewer regions, plus AWS and Azure Omni locations). A component with no price in your region fails with a message naming where it is priced.
- The report shows the region, the retrieval date and time, the SKU and rate of every price used, and that these are **public list prices** (no negotiated prices).
  The API can serve prices up to 12 hours old.

## Calculation

| Component | Formula |
|---|---|
| Storage | `GiB held x min(duration, 1 month) x 730 / 721` = GiB-months (the catalog defines 1 GiB-month as 721 hours of holding; an average month has 730); `tier_cost(GiB-months, free already used)`; physical billing uses the physical SKU |
| On-demand | `queries per month x billed bytes per query` converted to TiB; billed per query = `max(avg rounded up to a MiB, 10 MiB x tables per query)`; `tier_cost(TiB, free already used)` |
| Enterprise, baseline | `slots rounded up to a multiple of 50 x hours per day x days per month` slot-hours x the slot-hour rate |
| Enterprise, autoscale | `slots rounded up to a multiple of 50 x utilization x hours x days` slot-hours x the rate (with utilization 1 this is the ceiling) |
| BI Engine | `capacity GiB x hours per day x days per month` GiB-hours x the GiB-hour rate |
| Streaming | `MiB per month x the MiB rate` (no free tier) |
| Storage API write | `tier_cost(GiB per month, free already used)`; the first 2,048 GiB a month are free |
| Annual | 12 x monthly |

- **Free tiers are applied once per SKU, to the whole monthly quantity**, never per input. Storage and on-demand each have their own allowance. Annual is 12 x monthly because the
  allowance resets every month; it is not applied once a year.
- Costs are not assumed to scale linearly with anything: every line is computed from the quantities you give, with the billing rules above.
- A storage duration over one month does not change the monthly figure (it is the steady monthly cost); the report adds the total over the whole duration.

## Assumptions and limits

- Prices are public list prices, not negotiated prices, and exclude taxes and support.
- Usage repeats every month; the same inputs apply to the whole year.
- Storage is treated as active (modified within 90 days); long-term storage is cheaper, so storage is an upper bound for old data. Under physical billing, enter the size including time-travel and fail-safe bytes if they should count.
- Every query is assumed to process the average amount; real workloads with a few very large queries cost more per average byte. The 10 MiB minimum applies per query and per referenced table (docs), so set `tables_per_query` for small multi-table queries.
- The docs do not say how billed bytes above the minimum are rounded; rounding up to a whole MiB is an assumption with a negligible effect.
- Enterprise is the pay-as-you-go rate (commitments are not modelled). The reservation is assumed to exist only during the stated operating hours; baseline slots bill for every minute a reservation exists; autoscale bills the slots it scales to, with a one-minute minimum, which an hours-per-day input cannot model.
- Baseline and autoscale slots are both rounded up to a multiple of 50 (documented, except where excess commitments cover them, which is not modelled); a warning says when this happened.
- The docs do not state whether baseline is billed per second or per minute; the estimate bills the stated operating hours.
- BI Engine does not reduce the on-demand figure (an upper bound): the documentation pages that could be read do not say whether accelerated queries are billed for bytes, and the pricing page could not be retrieved. Set the query volume to what you expect to be billed by bytes, and confirm with `total_bytes_billed` on a real job.
- The on-demand and Enterprise lines are independent: leave out of the query input the work that runs on a reservation.
- Storage API reads, Data Transfer Service, network egress, other editions and other Google Cloud services are not estimated.
- Streaming: enter the size as billed (the billing export's usage amount). Rows count at least 1 KB each, so tiny rows bill more than their payload.

## Layout

```
config.py            service IDs, environment variable names, units, billing constants (no prices)
pricing_api.py       Catalog API client, SKU rules, price book, errors
usage_inputs.py      expected usage: parsing, unit conversion, validation
cost_calculator.py   the four cost components and the monthly and annual totals
report_generator.py  Markdown and JSON "Estimated Future Cost" report
main.py              CLI: estimate, prices
example_usage.json   sample inputs
tests/               147 pytest tests, no network (recorded catalog fixture, mocked API)
```

## What has been verified (25 Nov 2026)

| Item | Evidence | Status |
|---|---|---|
| Prices from the Catalog API | live calls with Application Default Credentials; the public Pricing API `v1beta` returned the same list prices for the same SKUs | verified |
| API-key transport | the real API answered a call with an invalid key in the `x-goog-api-key` header with HTTP 400 "API key not valid", and the same call without credentials with HTTP 403; the estimator reported both without leaking the key | request path verified; **a valid key was not available, so the success case is untested** |
| Baseline and autoscale slots are multiples of 50 | docs, "Troubleshoot reservation management tasks": "Baseline slots can only be configured in multiples of 50, except when covered by excess commitments"; "Slots always autoscale to a multiple of 50" | verified in the docs |
| Autoscale is billed for scaled slots, per second, one-minute minimum by default | docs, slots autoscaling and workload management pages; fluid scaling removes the minimum | verified in the docs |
| Baseline is always charged, used or not | docs: "Baseline slots are always charged" | verified in the docs |
| Baseline billing unit (second or minute), minimum baseline size | not stated in the docs | **not verified** |
| Commitment discounts | docs: 1-year 20%, 3-year 40% for Enterprise, and commitments do not apply to autoscale slots; the catalog's commitment SKUs match | consistent, not used by the estimator |
| BI Engine and Editions slots | docs (BI Engine monitoring): "accelerated BI Engine input stages are not counted towards slot reservations" | verified in the docs |
| BI Engine and on-demand bytes | not stated in the documentation pages that could be read; the pricing page could not be retrieved. A search-result summary of that page says accelerated stages are billed 0 scanned bytes, which is unconfirmed | **not verified** |
| Minimum billed per query and per referenced table | docs, 'Estimate and control costs': minimum 10 MiB "processed data per referenced table" and 10 MiB "processed data per query" | verified in the docs; applied |
| Free query tier scope | docs say "Each project is provided with 1 TB"; the catalog says ACCOUNT / MONTHLY and 1 TiB | **conflict, unresolved**; identical for one project |
| Rounding of billed bytes | not stated in the docs | assumption (up to a whole MiB) |
| Storage month | not stated in the docs; the catalog's unit factor is 2,595,600 seconds (721 hours) per GiB-month | applied from the catalog's own unit definition; **not confirmed against a bill** |
| Estimator against an independent calculation | 8 workloads priced from the raw live API response with separate code; 0 differences | verified |
| Region coverage | all 58 priced locations swept; found and fixed the EU multi-region naming bug | verified |
| Your account's prices and billing terms | the identity used here has none of nine billing permissions on the linked billing account; no billing or pricing export exists in the three projects it can read | **not verified** |

## Validating against your account

The estimates are list-price estimates. To validate them against your own terms:

1. **Contract prices.** A user with the Billing Account Viewer role (permission `billing.billingAccountPrice.get`) can run, with a token for that user:
   `curl -H "Authorization: Bearer $(gcloud auth print-access-token)" "https://cloudbilling.googleapis.com/v1beta/billingAccounts/BILLING_ACCOUNT_ID/skus/SKU_ID/price"`
   for each SKU in the report. The response shows `listPrice`, `contractPrice`, `effectiveDiscountPercent` and `priceReason` per tier. A `priceReason` of `default-price` and no discount means the list prices used here are your prices.
2. **A real API key** (needs a user who may create keys; the tool never creates one): create a key restricted to the Cloud Billing API, export it as `GCP_BILLING_API_KEY`, and run `python scripts/cost_estimator/main.py prices`. The output should match the Application Default Credentials result.
3. **Billing terms.** Ask a billing administrator whether the account has a custom pricing contract or capacity commitments. The pricing export (`cloud_pricing_export`) also carries `billing_account_price` next to the list price once it is enabled.
4. **BI Engine on-demand bytes.** The definitive check is one real job: reserve a small BI Engine capacity for an hour, run a query the capacity can accelerate, and read `total_bytes_billed` and `bi_engine_statistics` from `INFORMATION_SCHEMA.JOBS_BY_PROJECT`. This creates a billable reservation, so it needs an explicit decision.
