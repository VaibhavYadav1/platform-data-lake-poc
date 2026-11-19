# POC B – CRM Data Model and Integration
## Complete Requirements, Dependencies, Architecture, Technical Design and Execution Guide

**Project:** Store Alert Data Lake – Phase 2  
**POC:** B – One Source of Record for Customers  
**Plan version:** Phase 2 approved plan v2.0  
**Plan date:** 17 November 2026  
**Environment:** GCP sandbox – `data-lake-poc-512405`, `us-central1`  
**Primary technologies:** Google Cloud Storage, BigQuery, Cloud Run Jobs, Python, dbt, SQL

---

# 1. Executive Summary

## 1.1 Purpose

POC B establishes the CRM as the single authoritative source for customer and account information in the Store Alert Data Lake.

The objective is to ensure that every customer, store, and work order is associated with a consistent CRM-based definition of the customer. The data warehouse must not independently decide whether an account is a customer. That decision must come from the CRM customer type and status, using one shared business rule.

POC B also establishes a stable `tenant_id` for every customer organization. This identifier will later be used by POC D to enforce tenant-level data isolation.

## 1.2 Business problem

The warehouse receives operational data from different systems, including G2 and CRM.

G2 contains operational store and device information, while CRM contains account ownership, customer classification, store relationships, and work-order information.

Without a centralized customer definition, different datasets or models could classify the same organization differently. For example:

- A customer account should be recognized as a customer.
- A vendor account should not be treated as a customer.
- A partner account should not be treated as a customer.
- A prospect should not be treated as a customer.
- Multiple stores belonging to the same customer organization must resolve to the same tenant.

POC B solves this by making CRM the source of truth for customer classification and tenant assignment.

## 1.3 Expected outcome

At the end of POC B:

1. CRM exports are generated hourly.
2. CRM exports are automatically loaded into BigQuery.
3. Re-running the loader does not load the same export twice.
4. Account, store, and work-order records are available through staging and intermediate models.
5. A change affecting more than 50% of accounts is held for human review.
6. A single customer classification rule is implemented.
7. `dim_account` contains standardized CRM account information.
8. G2 stores are mapped to their corresponding CRM accounts and top-level CRM accounts.
9. `dim_store` is enriched with `tenant_id` and `is_customer_store`.
10. `fct_work_order` is created.
11. AT-19, AT-20, and AT-21 pass.

## 1.4 POC B in simple terms

Think of CRM as the official customer register.

- CRM tells us which organizations are customers, vendors, partners, or prospects.
- CRM tells us which account owns a store.
- The account hierarchy tells us which top-level organization the store belongs to.
- The top-level account ID becomes the store's `tenant_id`.
- That tenant ID becomes the basis for separating customer data in later security implementation.

The warehouse therefore has one consistent customer definition instead of independently interpreting customer information in multiple places.

---

# 2. Scope and Requirements

## 2.1 In scope

| Area | Requirement |
|---|---|
| CRM export | Generate hourly snapshots of accounts, stores, and work orders |
| Export integrity | Generate a manifest containing file names, sizes, and MD5 checksums |
| Data ingestion | Load complete CRM export folders into BigQuery |
| Idempotency | Avoid loading an export folder more than once |
| Load tracking | Maintain a log of export processing status |
| Data validation | Validate manifest completeness, file sizes, and checksums |
| Incremental processing | Maintain current CRM records through watermark-based merges |
| Customer classification | Implement one shared definition of a customer |
| Account dimension | Build `dim_account` from CRM data |
| Tenant assignment | Map G2 stores to top-level CRM accounts |
| Store enrichment | Add `tenant_id` and `is_customer_store` to `dim_store` |
| Work orders | Build `fct_work_order` from CRM work-order records |
| Change protection | Hold exports when more than half of accounts change |
| Testing | Pass AT-19, AT-20, and AT-21 |

## 2.2 Out of scope

The following are not core POC B deliverables:

- Replacing the existing G2 ingestion pipeline.
- Creating an entirely new G2 store dimension.
- Creating the core `dim_store` independently of POC C.
- Implementing tenant row access policies. These belong to POC D.
- Implementing a type-2 history snapshot of `dim_store`. This is B10 stretch work.
- Integrating a real CRM host database or production CRM change-data-capture system.
- Building a complete CRM application.

The POC uses generated CRM exports as a stand-in for the client's actual CRM system.

## 2.3 Business rules

1. CRM is the authoritative source for customer classification.
2. Only an account with customer type `CUSTOMER` and status `Active` counts as a customer.
3. Vendors, partners, and prospects are not customers.
4. Unknown customer type codes must not be classified as customers.
5. Every customer tenant is identified using the top-level CRM account ID.
6. A G2 store without an active matching CRM store record must not be assigned a tenant.
7. Stores associated with non-customer accounts must not be exposed as customer stores.
8. Personal contact information must not flow beyond the staging layer in its original form.

---

# 3. Architecture Overview

## 3.1 High-level architecture

POC B receives CRM export files through Google Cloud Storage, loads them into BigQuery, transforms the data through dbt, and creates the customer and tenant-related warehouse outputs.

```text
                 CRM Source Simulator
                         |
              Hourly CRM Export Files
          account.csv / store.csv / work_order.csv
                         |
                         v
                  Google Cloud Storage
                  crm/export_ts=.../
                         |
                    manifest.json
                         |
                         v
                 Cloud Run Job
                  poc-crm-loader
                         |
              Manifest and checksum checks
                         |
                 Change-size guard
                         |
                         v
                     BigQuery
                      raw_crm
                         |
                         v
                    Staging Models
                    stg_crm__*
                         |
                         v
                 Intermediate Models
                    int_crm__*
                         |
             +-----------+-----------+
             |                       |
             v                       v
         dim_account           CRM store data
                                     |
raw_g2 G2 store data ---------------+
                                     |
                                     v
                              int_store__tenant
                                     |
                                     v
                               dim_store
                             (POC C dimension)

CRM work orders
       |
       v
int_crm__work_order
       |
       v
fct_work_order
```

## 3.2 Main components

| Component | Responsibility |
|---|---|
| CRM source simulator | Generates hourly account, store, and work-order exports |
| Google Cloud Storage | Stores export folders and manifests |
| `poc-crm-loader` | Validates and loads CRM exports |
| `raw_crm` | Stores raw CRM export history and load tracking |
| Staging models | Apply data typing and remove or tokenize personal data |
| Intermediate models | Maintain current CRM records through incremental merges |
| `map_customer_type` | Defines CRM customer type mappings |
| `is_customer()` macro | Implements the shared customer definition |
| `dim_account` | Provides standardized account information |
| `int_store__tenant` | Resolves G2 stores to top-level CRM accounts |
| `dim_store` | Receives tenant and customer-store information |
| `fct_work_order` | Provides CRM work-order information |

---

# 4. Dataset and Table Dependencies

POC B is not an isolated pipeline. It consumes existing datasets and produces tables that other POCs require.

## 4.1 Upstream dataset dependencies

| Dependency | Dataset / table / component | Purpose | Required before |
|---|---|---|---|
| G2 source data | `raw_g2` | Supplies G2 store records and `g2_store_id` values | B7 |
| CRM export files | GCS `crm/export_ts=*/` | Supplies hourly CRM snapshots | B3 |
| CRM manifest | `manifest.json` | Verifies export completeness and file integrity | B3 |
| CRM landing tables | `raw_crm.account_landing`, `raw_crm.store_landing`, `raw_crm.work_order_landing` | Store imported CRM records | B4 |
| CRM load tracking | `raw_crm.load_log` | Prevents duplicate loading and tracks load status | B3 |
| dbt foundation | Existing dbt project and configured BigQuery targets | Provides models, materialisations, tests, and environments | B4, B6 |
| Customer type mapping | `map_customer_type` | Maps CRM type codes to standard classifications | B6 |
| Core store dimension | `dim_store` from POC C task C2 | Provides G2 store dimension to enrich | B7 |
| Tenant access mapping | `map_tenant_access` | Used to validate tenant assignments in AT-19 | B8 |

### Important distinction: `raw_g2` versus `dim_store`

- `raw_g2` provides the underlying G2 store records used for matching.
- `dim_store` is the warehouse dimension created by POC C, task C2.
- POC B uses G2 data and CRM data to calculate tenant assignment.
- POC B then enriches the existing POC C `dim_store`.

POC B does not create the core `dim_store` from scratch.

## 4.2 POC B table inventory

| Layer | Dataset / table | Upstream dependency | Purpose |
|---|---|---|---|
| Raw | `raw_crm.account_landing` | `account.csv` | Stores account export history |
| Raw | `raw_crm.store_landing` | `store.csv` | Stores CRM store export history |
| Raw | `raw_crm.work_order_landing` | `work_order.csv` | Stores work-order export history |
| Raw | `raw_crm.load_log` | CRM loader | Tracks export processing |
| Staging | `stg_crm__account` | `raw_crm.account_landing` | Types and tokenizes account data |
| Staging | `stg_crm__store` | `raw_crm.store_landing` | Prepares CRM store records |
| Staging | `stg_crm__work_order` | `raw_crm.work_order_landing` | Prepares work-order records |
| Intermediate | `int_crm__account` | `stg_crm__account` | Incrementally merges account changes |
| Intermediate | `int_crm__store` | `stg_crm__store` | Incrementally merges store changes |
| Intermediate | `int_crm__work_order` | `stg_crm__work_order` | Incrementally merges work-order changes |
| Intermediate | `int_store__tenant` | `raw_g2`, `int_crm__store`, `int_crm__account`, `map_customer_type` seed and `is_customer()` macro (or `dim_account`) | Resolves G2 store tenant and customer-store flag |
| Warehouse | `dim_account` | `int_crm__account`, seed, macro | Standardized account dimension |
| Warehouse | `dim_store` (enriched) | POC C `dim_store`, `int_store__tenant` | Adds tenant and customer-store information |
| Warehouse | `fct_work_order` | `int_crm__work_order`, `int_store__tenant`, `dim_account` | Work-order fact |

## 4.3 Downstream dependencies

| Downstream component | Depends on POC B outputs | Purpose |
|---|---|---|
| POC C – dbt transformation layer | `dim_account`, enriched `dim_store`, `fct_work_order` | Uses standardized customer and tenant information. POC C task C2 creates the core `dim_store`; POC B task B7 then supplies its tenant columns |
| POC D – tenant security | `dim_account`, `dim_store.tenant_id`, `dim_store.is_customer_store`, `map_tenant_access` | Enforces tenant-level data isolation |
| POC E – production orchestration | CRM loader, CRM models, freshness checks | Runs and monitors CRM ingestion and transformations |
| POC F – performance and cost | Published warehouse tables, including `fct_work_order` | Evaluates query performance and cost |

## 4.4 Table dependency flow

### A. Account processing

```text
account.csv
    |
    v
raw_crm.account_landing
    |
    v
stg_crm__account
    |
    v
int_crm__account
    |
    v
map_customer_type
    |
    v
is_customer() macro
    |
    v
dim_account
```

### B. Store-to-tenant assignment

```text
raw_g2 G2 stores
       |
       | Match using g2_store_id
       v
int_crm__store
       |
       | Obtain account_id
       v
int_crm__account
       |
       | Follow parent_account_id
       v
Top-level CRM account
       |
       | Use top-level account_id as tenant_id
       | Apply is_customer() to the top-level account
       v
int_store__tenant
       |
       v
dim_store (POC C)
```

### C. Work-order processing

```text
work_order.csv
       |
       v
raw_crm.work_order_landing
       |
       v
stg_crm__work_order
       |
       v
int_crm__work_order
       |
       | Resolve tenant_id and store_id
       | (int_store__tenant)
       v
fct_work_order
```

## 4.5 Cross-POC execution dependencies

| Task | Dependency | Explanation |
|---|---|---|
| B1 | None | CRM export specification can be finalized independently |
| B2 | 0.6 and B1 | Simulator needs the foundation and export specification |
| B3 | B2 | Loader needs generated export folders |
| B4 | B3 and 0.4 | Transformation models need loaded data and dbt foundation |
| B5 | B3 | Change-size guard is implemented in the loader |
| B6 | B1; B4 may be stubbed | Customer classification can begin before the final account model exists |
| B7 | B6 and C2 | Tenant assignment needs account classification and the core store dimension |
| B8 | B6 and B7 | Customer definition and tenant assignment must exist before AT-19 |
| B9 | B4 | Work-order fact requires the intermediate work-order model. Populating `tenant_id` and `store_id` also needs the B7 output (`int_store__tenant`) |
| B10 | G7 passed | Optional type-2 history work |

**Parallel work:** B6 may start using a stub for B4. B5 can be developed after the loader exists. B7 must wait for B6 and POC C's C2 `dim_store`.

---

# 5. Prerequisites and Environment Setup

## 5.1 Foundation prerequisites

The approved plan identifies tasks 0.4, 0.6 and 0.7 as prerequisites for POC B (0.6 for B2, 0.4 for B4, and 0.7 for the shared specifications).

| Prerequisite | Why it is needed |
|---|---|
| 0.6 – Foundation/source simulator setup | Provides the simulator foundation needed by the CRM export writer |
| 0.7 – Specifications | Defines the agreed source specifications, schemas, conventions, and type codes |
| 0.4 – dbt foundation | Required for staging and intermediate dbt models |
| GCS bucket | Stores CRM export folders |
| BigQuery datasets | Store raw, staging, intermediate, and warehouse data |
| Cloud Run job capability | Runs `poc-crm-loader` |
| Service account and IAM configuration | Allows the loader to access required GCS and BigQuery resources |
| Existing `raw_g2` | Provides G2 store information |
| POC C task C2 | Creates the core `dim_store` needed for B7 |

The exact service account names, IAM bindings, environment variable names, and deployment commands are not specified in the approved POC B task notes. They must be taken from the project's actual infrastructure configuration rather than invented.

## 5.2 Required source schemas

The CRM simulator must produce three files.

### `account.csv`

| Column | Description |
|---|---|
| `account_id` | Unique CRM account identifier |
| `account_name` | Account name |
| `customer_type_code` | CRM account classification code |
| `status` | Account status |
| `parent_account_id` | Parent account reference |
| `primary_contact_name` | Primary contact name |
| `primary_contact_email` | Primary contact email |
| `updated_at` | Time the account record was updated |
| `export_ts` | Export timestamp |

### `store.csv`

| Column | Description |
|---|---|
| `crm_store_id` | Unique CRM store identifier |
| `account_id` | CRM account associated with the store |
| `g2_store_id` | Matching G2 store identifier |
| `status` | CRM store status |
| `updated_at` | Time the store record was updated |
| `export_ts` | Export timestamp |

### `work_order.csv`

| Column | Description |
|---|---|
| `work_order_id` | Unique work-order identifier |
| `account_id` | Associated CRM account |
| `crm_store_id` | Associated CRM store |
| `g2_device_id` | Associated G2 device identifier |
| `work_type` | Work-order category |
| `status` | Work-order status |
| `opened_at` | Work-order opening timestamp |
| `closed_at` | Work-order closing timestamp |
| `updated_at` | Time the work order was updated |
| `export_ts` | Export timestamp |

### Source-data rules

- Account records are not deleted; they become `Inactive`.
- CRM store records include their associated `account_id`.
- `g2_store_id` is required for the store-matching process.
- `g2_device_id` is part of the work-order source schema.
- The simulator must generate account type and status changes.
- The simulator must be able to plant an unknown customer type code.
- The simulator must support a `--big-change` option.

The ID patterns `ACC` plus five digits, `CST` plus five digits, and `WO` plus six digits appear as proposals in the schema document, not as approved requirements in the task table.

## 5.3 CRM export folder structure

```text
crm/
    export_ts=<timestamp>/
        account.csv
        store.csv
        work_order.csv
        manifest.json
```

The manifest must be written last. It must list each export file with its file name, file size, and MD5 checksum.

The loader must not process an export until its manifest is available and all listed files pass validation.

---

# 6. Detailed Data Model

## 6.1 Raw layer – `raw_crm`

The raw layer preserves CRM export history.

| Table | Source | Purpose |
|---|---|---|
| `account_landing` | `account.csv` | Raw account export records |
| `store_landing` | `store.csv` | Raw CRM store export records |
| `work_order_landing` | `work_order.csv` | Raw work-order export records |
| `load_log` | Loader execution | Tracks processing status |

### Landing table behaviour

The loader must:

1. Load CSV data using explicit schemas.
2. Use `WRITE_APPEND`.
3. Skip the CSV header row.
4. Preserve the export timestamp.
5. Retain export history.
6. Record each load in `load_log`.

The raw landing tables are not the final customer or tenant tables. They are the source for downstream transformation.

### Load log

The approved plan requires a `load_log` entry containing the export folder, files, row counts, status, and processing time.

The exact physical column names and additional metadata fields should be finalized in the implementation.

The schema proposal also identifies possible additional fields such as account/store/work-order row counts, change ratio, approval information, error message, and loader execution identifier. These are proposed additions, not mandatory fields explicitly defined by the approved task table.

### Load statuses

| Status | Meaning |
|---|---|
| `LOADED` | Export successfully loaded |
| `HELD` | Export held for manual approval |
| `FAILED` | Export processing failed |

## 6.2 Staging layer

Models:

- `stg_crm__account`
- `stg_crm__store`
- `stg_crm__work_order`

### `stg_crm__account`

Responsibilities:

- Apply appropriate data types.
- Prepare account records for incremental processing.
- Replace `primary_contact_name` and `primary_contact_email` with `primary_contact_token`.
- Remove the original contact name and email columns.
- Preserve required business and lineage fields.

**Personal-data rule:** Contact name and email must not continue into the intermediate or warehouse layers in their original form.

### `stg_crm__store`

- Prepare CRM store records.
- Preserve the relationship between `crm_store_id`, `g2_store_id`, and `account_id`.
- Prepare store status and update timestamps for matching and merging.

### `stg_crm__work_order`

- Prepare work-order records.
- Preserve account, CRM store, and device references.
- Prepare work-order status and timestamps for downstream fact creation.

## 6.3 Intermediate layer

Models:

- `int_crm__account`
- `int_crm__store`
- `int_crm__work_order`
- `int_store__tenant`

### Watermark merge

The approved plan uses incremental dbt models with merge materialisation.

Example for `int_crm__account`:

```sql
{{ config(
    materialized = 'incremental',
    incremental_strategy = 'merge',
    unique_key = 'account_id'
) }}

select *
from {{ ref('stg_crm__account') }}

{% if is_incremental() %}
where updated_at > (
    select max(updated_at)
    from {{ this }}
)
{% endif %}

qualify row_number() over (
    partition by account_id
    order by export_ts desc, updated_at desc
) = 1
```

### Explanation

- `materialized = 'incremental'` means the model processes changes rather than rebuilding everything on each run.
- `incremental_strategy = 'merge'` updates existing records and inserts new ones.
- `unique_key = 'account_id'` identifies the account record to merge.
- The watermark uses `updated_at` to identify newer records.
- `row_number()` selects the latest available version for an account.

Equivalent intermediate models are required for CRM stores and work orders.

### Important watermark consideration

The approved example uses strict `updated_at > max(updated_at)` filtering.

Timestamp ties and late-arriving records should be tested. The example is the approved starting point, but the implementation must verify that the chosen watermark behaviour does not silently miss records with equal timestamps or delayed arrival.

## 6.4 Warehouse layer – `dim_account`

`dim_account` is the standardized CRM account dimension.

| Column | Purpose |
|---|---|
| `account_key` | Warehouse account key |
| `account_id` | CRM account identifier |
| `tenant_id` | Top-level CRM account ID |
| `account_name` | Account name |
| `customer_type_code` | Original CRM type code |
| `customer_type_enum` | Standardized type |
| `customer_type_name` | Readable type name |
| `is_customer` | Customer classification flag |
| `status` | CRM account status |
| `parent_account_id` | Parent CRM account |
| `primary_contact_token` | Tokenized primary contact reference |
| Lineage columns | Source and processing lineage |

The `is_customer` flag is derived from the shared customer definition. It must not be independently calculated using different rules in different models.

If the CRM provides an unknown customer type code, set the enum to `UNKNOWN`, set `is_customer = false`, and record the issue through DQ36.

---

# 7. Customer Classification

## 7.1 Customer type mapping

The dbt seed is `seeds/map_customer_type.csv`.

```csv
customer_type_code,customer_type_enum,customer_type_name,counts_as_customer
100000000,CUSTOMER,Customer,true
100000001,VENDOR,Vendor,false
100000002,PARTNER,Partner,false
100000003,PROSPECT,Prospect,false
```

| CRM code | Enum | Description | Customer? |
|---|---|---|---|
| `100000000` | `CUSTOMER` | Customer | Yes |
| `100000001` | `VENDOR` | Vendor | No |
| `100000002` | `PARTNER` | Partner | No |
| `100000003` | `PROSPECT` | Prospect | No |
| Unknown | `UNKNOWN` | Unrecognized type | No |

## 7.2 Shared `is_customer()` macro

```sql
{% macro is_customer(type_enum_col, status_col) -%}
  (
    {{ type_enum_col }} = 'CUSTOMER'
    and {{ status_col }} = 'Active'
  )
{%- endmacro %}
```

An account is a customer only if both conditions are true:

1. Its standardized type is `CUSTOMER`.
2. Its status is `Active`.

| Type | Status | `is_customer` |
|---|---|---|
| CUSTOMER | Active | TRUE |
| CUSTOMER | Inactive | FALSE |
| VENDOR | Active | FALSE |
| PARTNER | Active | FALSE |
| PROSPECT | Active | FALSE |
| UNKNOWN | Active | FALSE |

## 7.3 Single definition principle

The CI script `scripts/ci/check_single_definition.py` checks that the literal `'CUSTOMER'` and code `100000000` appear only in the approved seed and macro.

This prevents different models from implementing different customer definitions.

---

# 8. Tenant Assignment

## 8.1 Purpose

Tenant assignment determines which customer organization owns each G2 store.

The tenant is not necessarily the store's direct CRM account. A CRM account may be a child account of another account. In such cases, the tenant is the top-level account.

## 8.2 Source dependencies

The process uses:

- G2 store data from `raw_g2`.
- CRM store data from `int_crm__store`.
- CRM account data from `int_crm__account`.
- Customer classification from the `map_customer_type` seed and the shared `is_customer()` macro (the same definition exposed by `dim_account`).

## 8.3 Matching process

The approved path is:

**G2 store → active CRM store → CRM account → top-level CRM account**

1. Read the G2 store record.
2. Match it to an active CRM store record using `g2_store_id`.
3. Retrieve the CRM `account_id` associated with that CRM store.
4. Find the account in `int_crm__account`.
5. Follow `parent_account_id` until the top-level account is reached.
6. Use the top-level account ID as `tenant_id`.
7. Determine whether the top-level account qualifies as a customer.
8. Set `is_customer_store` accordingly.

### Example

```text
ACC00001 – Top-level customer account
    |
    +-- ACC00002 – Regional account
            |
            +-- ACC00003 – Store account
```

A store associated with `ACC00003` receives:

```text
tenant_id = ACC00001
```

This is an illustrative hierarchy, not a prescribed CRM account ID format.

## 8.4 `int_store__tenant`

The schema proposal identifies these columns:

| Column | Purpose |
|---|---|
| `store_id` | G2 store identifier |
| `crm_store_id` | Matched CRM store identifier |
| `account_id` | Associated CRM account |
| `tenant_id` | Top-level CRM account ID |
| `hierarchy_depth` | Number of account hierarchy levels |
| `is_customer_store` | Whether the store belongs to a customer |
| `tenant_reason` | Explanation of tenant assignment |
| `_source_updated_at` | Source update timestamp |

`hierarchy_depth` and `tenant_reason` are proposed schema fields and should be confirmed in `specs.md`.

## 8.5 Missing CRM store record

If a G2 store has no active matching CRM store record:

- `tenant_id = NULL`
- `is_customer_store = false`
- Generate a DQ37 warning.
- Keep the store available for internal investigation.
- Do not assign it to a customer tenant.

A null tenant matches no tenant access policy.

## 8.6 Non-customer account

A store can have a valid CRM store record but belong to a vendor, partner, or prospect.

In that situation:

- The account relationship may be resolved.
- `is_customer_store` must be false.
- It must not be treated as a customer store.
- No tenant principal should be mapped to that non-customer account.

## 8.7 `dim_store` enrichment

The core `dim_store` is created by POC C task C2. POC B task B7 enriches it with `tenant_id` and `is_customer_store`, using `int_store__tenant`.

---

# 9. CRM Work-Order Fact

## 9.1 Purpose

POC B also brings work orders from CRM into the warehouse. Work orders represent operational tasks associated with accounts, stores, and potentially devices.

## 9.2 Data flow

```text
work_order.csv
      |
      v
raw_crm.work_order_landing
      |
      v
stg_crm__work_order
      |
      v
int_crm__work_order
      |
      v
fct_work_order
```

## 9.3 Expected fields

| Column | Purpose |
|---|---|
| `work_order_id` | CRM work-order identifier |
| `tenant_id` | Customer tenant |
| `account_id` | CRM account |
| `crm_store_id` | CRM store |
| `store_id` | G2 store |
| `device_id` | G2 device |
| `work_type` | Work-order type |
| `status` | Work-order status |
| `opened_at` | Opening timestamp |
| `closed_at` | Closing timestamp |
| `opened_date` | Date derived from opening timestamp |
| `is_open` | Whether the work order remains open |
| DQ and lineage fields | Data quality and source traceability |

The `is_open` field is a proposed addition in the schema document.

## 9.4 Physical design

The approved task requires partitioning on `opened_date`.

The schema proposal additionally suggests clustering on `tenant_id`, `store_id`, and `device_id`. Clustering should be confirmed against the final physical-design specification.

## 9.5 Referential-integrity issue to resolve

The schema proposal describes retaining unknown account, store, or device references and flagging them through DQ47. However, it also describes `account_id` as non-null and as a foreign key to `dim_account`.

These requirements may conflict when an incoming work order references an unknown account.

The implementation must resolve this explicitly before building the final fact:

- Decide whether unknown references are retained and flagged.
- Decide how the required account relationship is represented.
- Ensure the source account identifier is not silently overwritten.
- Keep the DQ47 behaviour consistent with the approved decision.

Do not assume both requirements can be satisfied without a defined handling strategy.

---

# 10. CRM Export Simulator – Task B2

## 10.1 Objective

Create a simulator that generates CRM export folders on an hourly basis. The simulator acts as a stand-in for the client's CRM export system.

## 10.2 Required behaviour

1. Generate hourly snapshots.
2. Produce `account.csv`.
3. Produce `store.csv`.
4. Produce `work_order.csv`.
5. Generate account type changes.
6. Generate account status changes.
7. Generate at least one unknown customer type code for testing.
8. Support the `--big-change` option.
9. Write `manifest.json` last.

## 10.3 Big-change simulation

The `--big-change` option must generate a scenario where more than half of the accounts change. This is required to validate DQ42. The approved acceptance scenario uses a 60% change.

## 10.4 Completion criteria

B2 is complete when an export folder is generated every hour and the manifest is present and complete.

---

# 11. CRM Loader – Task B3

## 11.1 Objective

Implement a Python Cloud Run Job named `poc-crm-loader`. The job loads new, complete CRM export folders into BigQuery.

The code belongs in `loaders/crm/`.

## 11.2 Loader responsibilities

- Discover new export folders.
- Check manifest availability.
- Validate every file.
- Check file size and MD5.
- Apply the change-size guard.
- Load CSV files into their landing tables.
- Avoid duplicate processing.
- Record load status.
- Clean up partially loaded records after failure.

## 11.3 Execution sequence

### Step 1: Discover exports

List `crm/export_ts=*/manifest.json` in the bucket.

### Step 2: Check load history

Check `raw_crm.load_log`. Skip folders whose status is already `LOADED`.

### Step 3: Handle held folders

Stop at the first folder marked `HELD`. Later exports must wait behind it. This prevents the processing watermark from jumping ahead of an export that has not yet been approved. An approved held export is released for loading (see section 12.4).

### Step 4: Process oldest first

Process new export folders in chronological order.

### Step 5: Validate manifest

For every export:

- Confirm all files exist.
- Confirm file sizes match.
- Confirm MD5 checksums match.

Reuse the validation approach from `upload-file-validator-data-lake-poc`.

### Step 6: Run the change-size guard

Apply DQ42 before loading the folder. If the guard holds the folder, load nothing, record the folder as `HELD` in `load_log`, and stop processing later folders.

### Step 7: Load CSV files

| File | Landing table |
|---|---|
| `account.csv` | `raw_crm.account_landing` |
| `store.csv` | `raw_crm.store_landing` |
| `work_order.csv` | `raw_crm.work_order_landing` |

The approved loading configuration is `WRITE_APPEND`, explicit schema, and `skip_leading_rows=1`.

### Step 8: Handle partial failure

If any file fails:

1. Delete the rows associated with that export timestamp from the landing tables.
2. Mark the folder `FAILED`.
3. Do not treat the export as successfully loaded.
4. Allow the next loader execution to retry it.

### Step 9: Write load log

Record the folder, files, row counts, status, and processing time.

## 11.4 Idempotency

The loader must be safe to run repeatedly.

- First run: export is loaded.
- Second run: the same export is detected as already loaded.
- Second run: no duplicate rows are loaded.

This is verified by AT-20.

## 11.5 Shared raw dataset behaviour

The approved plan specifies:

- The `dev` micro-batch starts the CRM loader on every run.
- The `int` micro-batch does not run it.
- The `int` configuration uses `run_crm_loader = false`.

The reason is that `raw_crm` is shared. The CRM export should not be independently loaded again by the integration environment.

---

# 12. Change-Size Guard – Task B5

## 12.1 Purpose

The change-size guard protects the warehouse from unexpectedly large CRM changes.

A large change could indicate an accidental bulk update, an incorrect export, a source-system problem, a simulator defect, or an unexpected change in customer classification or account data.

Instead of automatically loading a suspicious export, the loader holds it for review.

## 12.2 Change calculation

The guard compares the current `account.csv` with the previous successfully loaded export.

Changed rows include:

1. Rows whose `(account_id, updated_at)` pair is new.
2. Accounts that disappeared from the previous export. Under the source-data rule that accounts are never deleted (they become `Inactive`), a disappearing account is itself anomalous and is counted as a change.

\[
\text{Change Ratio} =
\frac{\text{Changed Rows}}
{\text{Rows in Previous Export}}
\]

## 12.3 Threshold

**Approved threshold: greater than 50%.**

If the ratio is greater than 0.5:

- Mark the export `HELD`.
- Load nothing from that export.
- Log a structured error.
- Trigger the alert policy.

The structured log event is:

```json
{
  "event": "crm_guard_tripped"
}
```

The E7 alert policy emails the team.

## 12.4 Approval process

A person must review the export before approving it. Approval releases the held export so the loader can validate and load it on its next run (after which it is recorded as `LOADED`), and later exports can then proceed in order.

```bash
poc-crm-loader --approve export_ts=<timestamp>
```

The actual command-line implementation must follow the loader's configured argument interface.

## 12.5 Required unit tests

| Scenario | Expected result |
|---|---|
| 0% change | Load |
| 49% change | Load |
| 51% change | Hold |
| First-ever export | Load; no previous export exists for comparison |
| 60% simulated change | Hold and alert |

## 12.6 Processing order protection

If an export is held, later exports must wait. This is important because loading later exports first could cause the warehouse watermark to move ahead while an earlier export remains unresolved.

---

# 13. Data Quality and Error Handling

## 13.1 Approved POC B checks

| DQ ID | Condition | Severity | Expected behaviour | Location |
|---|---|---|---|---|
| DQ36 | Unknown CRM account type | Warning | Set enum to `UNKNOWN`, `is_customer=false` | `dim_account` |
| DQ37 | G2 store has no active CRM store record | Warning | Set tenant to NULL and customer-store flag to false | `int_store__tenant` |
| DQ40 | No new CRM export loaded in 75 minutes | Freshness error | Generate alert | Freshness check |
| DQ41 | Personal data appears in warehouse | Error | Fail build | Singular test and daily scan |
| DQ42 | More than half of CRM accounts change in one export | Error | Hold export and alert | `poc-crm-loader` |

DQ45–DQ47 appear as additional proposals in the schema document. They should not be treated as approved requirements unless formally confirmed. (The approved plan defines DQ33–DQ43.)

## 13.2 DQ36 – Unknown customer type

When an account has an unknown customer type code:

- Map it to `UNKNOWN`.
- Set `is_customer = false`.
- Record the warning.
- Do not grant it customer status.

## 13.3 DQ37 – Store without active CRM mapping

When a G2 store has no active CRM store record:

- Set `tenant_id = NULL`.
- Set `is_customer_store = false`.
- Keep it internal-only.
- Record a warning.

## 13.4 DQ40 – CRM export freshness

No new CRM export should be loaded for more than 75 minutes without detection. If the freshness requirement is violated, the freshness check must generate an alert.

## 13.5 DQ41 – Personal-data protection

The warehouse must not contain original personal contact data.

The check must detect:

- Deny-listed personal-data columns.
- Email-like values.

It must fail the build when a violation is detected.

## 13.6 DQ42 – Large CRM change

A change ratio above 50% must hold the export and trigger an alert.

## 13.7 Failure handling principles

1. Do not silently discard invalid records.
2. Do not mark a partially loaded export as successful.
3. Do not advance past a held export.
4. Record failure details.
5. Make retries safe.
6. Preserve enough lineage to identify the source export.
7. Keep customer classification conservative: unknown does not mean customer.

## 13.8 dbt test failures

The approved plan uses `dq_{env}` for dbt `store_failures`. Failing rows should be stored so that the team can investigate the records responsible for a failed test.

---

# 14. Security and Personal Data

## 14.1 Personal-data handling

CRM contains personal contact information. The approved design requires personal data to be tokenized before it moves beyond staging.

| Layer | Contact name/email |
|---|---|
| Raw landing | Original source values |
| Staging | Replaced by `primary_contact_token`; raw columns dropped |
| Intermediate | Token only |
| Warehouse | Token only |

## 14.2 Tokenization

The staging model replaces `primary_contact_name` and `primary_contact_email` with `primary_contact_token`.

The actual tokenization algorithm, key management implementation, and key table structure are not defined in the approved POC B task notes. They must follow the project's shared tokenization implementation and security design.

Do not invent a hashing or encryption algorithm as part of this document.

## 14.3 Customer and tenant security

POC B prepares the information needed by POC D. It does not implement the final row access policies itself.

POC B provides:

- Customer classification in `dim_account`.
- Tenant assignment in `dim_store`.
- Customer-store classification.
- Account relationships.

POC D uses these outputs to determine which tenant can access which records.

## 14.4 Vendor and partner isolation

Vendor and partner accounts must not be classified as customers.

The approved AT-19 scenario plants a vendor account linked to two stores. Both stores must have:

```text
is_customer_store = false
```

The POC D security suite must then prove that no customer tenant can see those stores.

---

# 15. Implementation Tasks and Ownership

## 15.1 Approved task breakdown

| ID | Task | Owner | Day | Dependencies | Completion condition |
|---|---|---|---|---|---|
| B1 | CRM export specification and type codes | Dev 5 | 1–2 | None | Included in `specs.md` |
| B2 | CRM export simulator | Dev 3 | 3–4 | 0.6, B1 | Hourly export folders generated |
| B3 | CRM loader | Dev 3 | 4–5 | B2 | Second run loads nothing |
| B4 | Staging and intermediate watermark models | Dev 3 | 5–6 | B3, 0.4 | AT-20 passes |
| B5 | Change-size guard and approval command | Dev 3 | 6–7 | B3 | AT-21 passes |
| B6 | Customer type seed, macro, and `dim_account` | Dev 5 | 3–4 | B1; B4 can be stubbed | Required fields and tests pass |
| B7 | Tenant assignment and store enrichment | Dev 5 | 4–5 | B6, C2 | Every store has a tenant or appears in DQ37 |
| B8 | AT-19 checks | Dev 5 | 5–6 | B6, B7 | AT-19 passes |
| B9 | `fct_work_order` | Dev 3 | 8 | B4 | Built and tested; partitioned on `opened_date` |
| B10 | Type-2 store history snapshot | Dev 5 | Stretch | G7 passed | Snapshot shows store moving account |

## 15.2 Developer responsibilities

### Dev 3

Responsible for:

- CRM export writer.
- CRM loader.
- Manifest and file validation.
- Load tracking.
- Change-size guard.
- CRM staging and intermediate models.
- Work-order fact.

### Dev 5

Responsible for:

- CRM export specification.
- Customer type mapping.
- `is_customer()` macro.
- `dim_account`.
- Tenant assignment.
- Store enrichment.
- AT-19.

## 15.3 Work coordination

The main coordination point is B7.

Dev 5 needs the following before tenant enrichment can be completed:

- CRM account classification from B6.
- CRM store and account intermediate models.
- Core `dim_store` from POC C C2.
- G2 store identifiers from `raw_g2`.

The work can be developed in parallel, but the final model cannot be completed until these dependencies are available.

## 15.4 Detailed task breakdown (B1–B10)

Each block below expands one row of the table in 15.1. Owners, days, dependencies and completion conditions are the approved values; sub-steps are drawn from the sections referenced in each block.

### B1 – CRM export specification and type codes

| Item | Detail |
|---|---|
| Owner / days | Dev 5 / day 1–2 |
| Depends on | None (part of task 0.7) |
| Blocks | B2, B6 |
| Detail sections | 5.2, 5.3, 7.1 |

**Sub-steps**
1. Define the columns, types and meaning of `account.csv`, `store.csv` and `work_order.csv`.
2. Record the source-data rules: accounts are never deleted (they become `Inactive`), stores carry `account_id`, `g2_store_id` is required.
3. Define the four known customer type codes (`100000000`–`100000003`) and the `UNKNOWN` fallback.
4. Define `export_ts` and `updated_at` behaviour.
5. Define the folder layout `crm/export_ts=<timestamp>/` and the `manifest.json` structure (file name, size, MD5; written last).
6. Confirm or reject the proposed ID patterns and optional fields listed in section 21.

**Output:** CRM export specification in `specs.md`.  
**Done when:** the specification is in `specs.md`.

### B2 – CRM export simulator

| Item | Detail |
|---|---|
| Owner / days | Dev 3 / day 3–4 |
| Depends on | 0.6, B1 |
| Blocks | B3 |
| Detail sections | 10, 5.2, 5.3 |

**Sub-steps**
1. Generate an hourly snapshot folder with `account.csv`, `store.csv` and `work_order.csv`.
2. Generate account type changes and status changes between snapshots.
3. Plant at least one unknown customer type code.
4. Implement `--big-change` so that 60% of accounts change (used by DQ42 and AT-21).
5. Compute file sizes and MD5 checksums and write `manifest.json` last.

**Output:** CRM export writer in the simulator; export folders in GCS.  
**Done when:** an export folder appears every hour with a complete manifest.

### B3 – CRM loader (`poc-crm-loader`)

| Item | Detail |
|---|---|
| Owner / days | Dev 3 / day 4–5 |
| Depends on | B2 |
| Blocks | B4, B5 |
| Detail sections | 11, 6.1 |

**Sub-steps**
1. Create the Python Cloud Run job in `loaders/crm/`.
2. List `crm/export_ts=*/manifest.json`.
3. Skip folders already `LOADED` in `raw_crm.load_log`; stop at the first `HELD` folder.
4. Process new folders oldest first.
5. Validate every file in the manifest (present, size, MD5), reusing the check from `upload-file-validator-data-lake-poc`.
6. Load each CSV into its landing table with `WRITE_APPEND`, an explicit schema and `skip_leading_rows=1`.
7. On any file failure, delete that export's rows from the landing tables, mark the folder `FAILED`, and leave it for retry.
8. Write the `load_log` row (folder, files, row counts, status, processing time).
9. Configure the `dev` micro-batch to start the loader and `int` to skip it (`run_crm_loader = false`).

**Output:** `poc-crm-loader` job, `raw_crm` landing tables, `raw_crm.load_log`.  
**Done when:** running the loader twice loads nothing the second time.

### B4 – Staging and intermediate watermark models

| Item | Detail |
|---|---|
| Owner / days | Dev 3 / day 5–6 |
| Depends on | B3, 0.4 |
| Blocks | B9 (and B6 final wiring) |
| Detail sections | 6.2, 6.3, 14.1, 16.2 |

**Sub-steps**
1. Create `stg_crm__account`, `stg_crm__store`, `stg_crm__work_order` with typing.
2. In `stg_crm__account`, replace contact name and email with `primary_contact_token` and drop the originals.
3. Create `int_crm__account`, `int_crm__store`, `int_crm__work_order` as incremental `merge` models on their unique keys with an `updated_at` watermark.
4. Keep the latest version per key using `row_number()` over `export_ts desc, updated_at desc`.
5. Test equal-timestamp and late-arriving records against the watermark.
6. Verify the re-run produces no duplicates.

**Output:** three `stg_crm__*` and three `int_crm__*` models.  
**Done when:** AT-20 passes (re-run loads nothing; five account changes change exactly five rows).

### B5 – Change-size guard and approval command

| Item | Detail |
|---|---|
| Owner / days | Dev 3 / day 6–7 |
| Depends on | B3 |
| Blocks | AT-21 |
| Detail sections | 12, 13.6, 16.3 |

**Sub-steps**
1. Compare the current `account.csv` with the previous successfully loaded export: new `(account_id, updated_at)` pairs plus disappeared accounts, divided by rows in the previous export.
2. Hold the export when the ratio is greater than 0.5: status `HELD`, nothing loaded, later exports wait.
3. Log the structured event `crm_guard_tripped` and connect it to the E7 alert policy (email within five minutes).
4. Add the approve command (`poc-crm-loader --approve export_ts=<timestamp>`) that releases a held export.
5. Unit tests: 0% load, 49% load, 51% hold, first-ever export load, 60% hold and alert.

**Output:** guard logic and approval command in the loader.  
**Done when:** AT-21 passes.

### B6 – Customer type seed, macro and `dim_account`

| Item | Detail |
|---|---|
| Owner / days | Dev 5 / day 3–4 |
| Depends on | B1 (B4 may be stubbed) |
| Blocks | B7, B8 |
| Detail sections | 6.4, 7, 13.2 |

**Sub-steps**
1. Create `seeds/map_customer_type.csv` with the four type codes.
2. Create the `is_customer()` macro (type `CUSTOMER` and status `Active`).
3. Build `dim_account` with `customer_type_code`, `customer_type_enum`, `customer_type_name`, `is_customer`, `tenant_id` (top-level account ID), `primary_contact_token` and lineage columns.
4. Map unknown codes to `UNKNOWN` with `is_customer = false` and raise DQ36.
5. Add `scripts/ci/check_single_definition.py` so `'CUSTOMER'` and `100000000` appear only in the seed and macro.
6. Add dbt tests for the required fields and the customer rule.

**Output:** seed, macro, `dim_account`, CI script.  
**Done when:** tests pass and `dim_account` has `customer_type_enum`, `customer_type_name`, `is_customer` and `tenant_id`.

### B7 – Tenant assignment and store enrichment

| Item | Detail |
|---|---|
| Owner / days | Dev 5 / day 4–5 |
| Depends on | B6, C2 |
| Blocks | B8, tenant fields on B9 |
| Detail sections | 8, 13.3 |

**Sub-steps**
1. Match G2 stores from `raw_g2` to active CRM stores in `int_crm__store` on `g2_store_id`.
2. Resolve the CRM `account_id` in `int_crm__account` and follow `parent_account_id` to the top-level account.
3. Set `tenant_id` to the top-level account ID and `is_customer_store` using the shared customer definition.
4. For stores with no active CRM store record, set `tenant_id = NULL`, `is_customer_store = false` and raise DQ37.
5. Publish `int_store__tenant`; confirm the proposed `hierarchy_depth` and `tenant_reason` columns.
6. Add `tenant_id` and `is_customer_store` to the POC C `dim_store`.
7. Agree handling of missing parents, hierarchy loops and multiple active matches (proposed DQ45, DQ46).

**Output:** `int_store__tenant`; enriched `dim_store`.  
**Done when:** every store has a tenant or is listed by DQ37.

### B8 – AT-19 checks

| Item | Detail |
|---|---|
| Owner / days | Dev 5 / day 5–6 |
| Depends on | B6, B7 |
| Blocks | Phase 2 sign-off; POC D isolation proof |
| Detail sections | 14.4, 16.1 |

**Sub-steps**
1. Test that every account with `is_customer = true` has type `CUSTOMER` and status `Active`.
2. Test that every tenant in `map_tenant_access` is a customer account.
3. Run `scripts/ci/check_single_definition.py`.
4. Plant a vendor account linked to two stores and confirm both have `is_customer_store = false`.
5. Run the POC D security suite, when available, to prove no tenant can see those stores.

**Output:** AT-19 tests.  
**Done when:** AT-19 passes.

### B9 – `fct_work_order`

| Item | Detail |
|---|---|
| Owner / days | Dev 3 / day 8 |
| Depends on | B4 (tenant and store fields also need B7) |
| Blocks | POC C task C10, POC F benchmarks |
| Detail sections | 9 |

**Sub-steps**
1. Read `int_crm__work_order`.
2. Resolve account, CRM store, G2 store and device references; take `tenant_id` and `store_id` from `int_store__tenant`.
3. Derive `opened_date` and partition the table on it (clustering and `is_open` pending confirmation).
4. Decide how unknown account, store or device references are kept and flagged (section 9.5, proposed DQ47) before finalizing constraints.
5. Add tests and lineage columns.

**Output:** `fct_work_order`.  
**Done when:** built and tested, partitioned on `opened_date`.

### B10 – Type-2 store history snapshot (stretch)

| Item | Detail |
|---|---|
| Owner / days | Dev 5 / stretch (no scheduled day) |
| Depends on | G7 passed |
| Blocks | Nothing |
| Detail sections | 2.2 |

**Sub-steps**
1. Add a dbt snapshot on `dim_store` tracking `tenant_id` and account changes (type 2 history).
2. Simulate a store moving to another account and run the snapshot.

**Output:** `dim_store` history snapshot.  
**Done when:** the snapshot shows a store moving account. Optional; do only if time remains after G7.

---

# 16. Acceptance Tests

POC B has three principal acceptance tests.

## 16.1 AT-19 – One definition of customer

**Objective:** Prove that the CRM customer definition is applied consistently and that non-customer accounts cannot become customer tenants.

### Test 1 – Customer classification

Every account where `is_customer = true` must have:

- `customer_type_enum = 'CUSTOMER'`
- `status = 'Active'`

### Test 2 – Tenant mapping

Every tenant in `map_tenant_access` must be a customer account.

### Test 3 – Single definition CI check

Run `scripts/ci/check_single_definition.py`.

The script verifies that:

- `'CUSTOMER'` appears only in the approved seed and macro.
- Code `100000000` appears only in the approved seed and macro.

### Test 4 – Vendor isolation

Plant a vendor account linked to two stores.

Expected:

- Both stores have `is_customer_store = false`.
- No tenant can see either store.
- POC D security tests prove the isolation.

**Acceptance condition: AT-19 passes.**

## 16.2 AT-20 – CRM watermark merge

**Objective:** Prove that CRM exports are loaded incrementally and repeated execution does not duplicate data.

### Test 1 – Re-run the same export

1. Generate a CRM export.
2. Run the loader.
3. Record the loaded state.
4. Run the loader again.

Expected:

- First run loads the export.
- Second run loads nothing.
- No duplicate rows are created.

### Test 2 – Five account changes

1. Record a fingerprint of `int_crm__account`.
2. Generate a subsequent export where five accounts change.
3. Run the loader and transformation models.
4. Compare the resulting account data.

Expected: exactly five account rows change in `int_crm__account`.

**Acceptance condition: AT-20 passes.**

## 16.3 AT-21 – Change-size guard

**Objective:** Prove that a suspiciously large CRM change is held until approved.

### Test sequence

1. Run the simulator with:

```bash
simulator crm-export --big-change
```

2. The simulator changes 60% of accounts.
3. The loader discovers the export.
4. The change-size guard calculates the change ratio.
5. The loader marks the export `HELD`.
6. No records from that export are loaded.
7. A structured error is logged.
8. The alert email is generated within five minutes.
9. A human reviews the export.
10. Run the loader with the approval argument.

Expected:

- The export is held before loading.
- No data from the held export is loaded.
- The alert is sent within five minutes.
- The export loads after approval.

**Acceptance condition: AT-21 passes.**

---

# 17. Execution Runbook

This section describes the practical sequence for implementing and validating POC B. The phases follow the dependency order and the approved day schedule in section 15.1.

## Phase 1 – Verify prerequisites

Before coding:

1. Confirm that tasks 0.4, 0.6 and 0.7 are complete.
2. Confirm the CRM source specification.
3. Confirm the BigQuery project and dataset configuration.
4. Confirm the GCS bucket and CRM export folder location.
5. Confirm the dbt project and target configuration.
6. Confirm that `raw_g2` is available.
7. Coordinate the POC C C2 `dim_store` dependency.
8. Review the existing tokenization approach.

**Expected result:** The team understands the required inputs, target tables, and environment dependencies.

## Phase 2 – Define CRM source schemas

Complete B1.

1. Define `account.csv`.
2. Define `store.csv`.
3. Define `work_order.csv`.
4. Define the four known customer type codes.
5. Define export timestamp and update timestamp behaviour.
6. Define manifest structure.
7. Add the specifications to `specs.md`.

**Expected result:** The simulator and loader can use one agreed source contract.

## Phase 3 – Build the simulator

Complete B2.

1. Implement the hourly CRM export writer.
2. Generate account data.
3. Generate CRM store data.
4. Generate work orders.
5. Generate account status changes.
6. Generate account type changes.
7. Add an unknown type code scenario.
8. Implement `--big-change`.
9. Generate checksums and file sizes.
10. Write the manifest last.

**Expected result:** Complete, repeatable CRM export folders are available in GCS.

## Phase 4 – Build the loader

Complete B3.

1. Create the Python Cloud Run job.
2. List export folders.
3. Read `raw_crm.load_log`.
4. Skip already loaded folders.
5. Stop at the first held folder.
6. Process new folders oldest first.
7. Validate the manifest.
8. Validate file sizes and checksums.
9. Load the CSV files into landing tables.
10. Implement cleanup on partial failure.
11. Write load tracking records.

**Expected result:** New CRM export folders are loaded safely and re-runs are idempotent.

## Phase 5 – Build CRM transformation models

Complete B4.

1. Create `stg_crm__account`.
2. Create `stg_crm__store`.
3. Create `stg_crm__work_order`.
4. Apply data typing.
5. Tokenize account contact information.
6. Remove original contact name and email columns.
7. Create `int_crm__account`.
8. Create `int_crm__store`.
9. Create `int_crm__work_order`.
10. Implement incremental merge logic.
11. Verify idempotency and watermark behaviour.

**Expected result:** CRM records are available in a standardized current-state form.

## Phase 6 – Implement change protection

Complete B5.

1. Read the previous successfully loaded account export.
2. Compare account ID and update timestamp pairs.
3. Identify disappeared accounts.
4. Calculate the change ratio.
5. Hold exports above 50%.
6. Write the structured log event.
7. Trigger the alert.
8. Implement manual approval.
9. Test 0%, 49%, 51%, and first-export scenarios.

**Expected result:** AT-21 passes.

## Phase 7 – Implement customer classification

Complete B6.

1. Create `map_customer_type`.
2. Implement `is_customer()` macro.
3. Create `dim_account`.
4. Populate customer type enum and name.
5. Derive `is_customer`.
6. Assign the top-level account identifier as the account's `tenant_id`.
7. Handle unknown type codes.
8. Add dbt tests.

**Expected result:** One standardized customer definition is available in `dim_account`.

## Phase 8 – Implement tenant assignment

Complete B7.

1. Read G2 store data from `raw_g2`.
2. Read CRM store records from `int_crm__store`.
3. Match using `g2_store_id`.
4. Resolve the associated CRM account.
5. Follow the account hierarchy to the top-level account.
6. Assign the top-level account ID as `tenant_id`.
7. Calculate `is_customer_store`.
8. Identify stores without an active CRM mapping.
9. Record DQ37 warnings.
10. Enrich the existing POC C `dim_store`.

**Expected result:** Every store has a tenant assignment or is explicitly reported as an exception.

## Phase 9 – Validate customer and tenant rules

Complete B8.

1. Run the customer classification tests.
2. Validate tenant mappings.
3. Run the single-definition CI script.
4. Plant a vendor account with two stores.
5. Confirm both stores are non-customer stores.
6. Run the POC D security suite when available.

**Expected result:** AT-19 passes.

## Phase 10 – Build work-order fact

Complete B9.

1. Read `int_crm__work_order`.
2. Resolve account, store, and device references.
3. Apply tenant assignment (from `int_store__tenant`, B7).
4. Create `fct_work_order`.
5. Add `opened_date`.
6. Partition on `opened_date`.
7. Apply tests and lineage.
8. Resolve the unknown-reference handling decision before finalizing constraints.

**Expected result:** The work-order fact is built and tested.

## Phase 11 – Final integration

1. Run the CRM simulator.
2. Run the loader.
3. Run dbt staging and intermediate models.
4. Run account and tenant models.
5. Build `fct_work_order`.
6. Run AT-19.
7. Run AT-20.
8. Run AT-21.
9. Verify DQ36, DQ37, DQ40, DQ41, and DQ42.
10. Confirm the downstream POC C and POC D dependencies are satisfied.

**Expected result:** POC B is ready for integration with the remaining Phase 2 work.

---

# 18. Expected Repository Structure

The approved task notes identify `loaders/crm/` and certain dbt seeds, macros, and CI scripts.

The following is a suggested logical organization, not a confirmed complete repository tree:

```text
project/
│
├── loaders/
│   └── crm/
│       └── CRM loader implementation
│
├── seeds/
│   └── map_customer_type.csv
│
├── macros/
│   └── is_customer.sql
│
├── models/
│   ├── staging/
│   │   └── crm/
│   │       ├── stg_crm__account.sql
│   │       ├── stg_crm__store.sql
│   │       └── stg_crm__work_order.sql
│   │
│   ├── intermediate/
│   │   ├── crm/
│   │   │   ├── int_crm__account.sql
│   │   │   ├── int_crm__store.sql
│   │   │   └── int_crm__work_order.sql
│   │   │
│   │   └── stores/
│   │       └── int_store__tenant.sql
│   │
│   └── marts/
│       ├── dim_account.sql
│       ├── dim_store.sql
│       └── fct_work_order.sql
│
├── scripts/
│   └── ci/
│       └── check_single_definition.py
│
├── simulator/
│   └── CRM export writer
│
└── specs.md
```

The exact folder layout must follow the existing repository conventions.

---

# 19. Deliverables

| Deliverable | Description |
|---|---|
| CRM export specification | Documented account, store, and work-order schemas |
| CRM simulator | Hourly export generation with test scenarios |
| CRM export folders | CSV files and manifest in GCS |
| CRM loader | `poc-crm-loader` Cloud Run job |
| Load tracking | `raw_crm.load_log` |
| Raw CRM tables | Account, store, and work-order landing tables |
| Staging models | Three `stg_crm__*` models |
| Intermediate models | Three `int_crm__*` models |
| Customer type seed | `map_customer_type` |
| Shared customer macro | `is_customer()` |
| Account dimension | `dim_account` |
| Tenant mapping model | `int_store__tenant` |
| Enriched store dimension | `dim_store` with tenant and customer-store columns |
| Work-order fact | `fct_work_order` |
| Data-quality checks | DQ36, DQ37, DQ40, DQ41, DQ42 |
| Acceptance tests | AT-19, AT-20, AT-21 |
| Technical documentation | Source schema, table dependencies, execution and test details |

---

# 20. Definition of Done

## CRM ingestion

- [ ] Hourly CRM exports are generated.
- [ ] Each export includes account, store, and work-order CSV files.
- [ ] Manifest is written last.
- [ ] File size and MD5 validation works.
- [ ] The loader processes new exports automatically.
- [ ] Re-running the loader does not duplicate an export.
- [ ] Failed exports are cleaned up and retried safely.
- [ ] Load history is recorded.

## Change protection

- [ ] Change ratio is calculated correctly.
- [ ] Exports above 50% change are held.
- [ ] Held exports are not loaded.
- [ ] Later exports wait behind held exports.
- [ ] Alert is generated.
- [ ] Manual approval releases the export.
- [ ] AT-21 passes.

## Customer definition

- [ ] Customer type seed is implemented.
- [ ] Shared `is_customer()` macro is implemented.
- [ ] `dim_account` is built.
- [ ] Unknown types are classified as `UNKNOWN`.
- [ ] Unknown types are not treated as customers.
- [ ] The single-definition CI check passes.

## Tenant assignment

- [ ] G2 stores are matched to active CRM store records.
- [ ] Account hierarchy is resolved.
- [ ] Top-level account ID is used as tenant ID.
- [ ] `dim_store` is enriched.
- [ ] Missing CRM store records are reported by DQ37.
- [ ] Non-customer stores are classified correctly.

## Work orders

- [ ] `int_crm__work_order` is built.
- [ ] `fct_work_order` is built.
- [ ] `opened_date` partitioning is implemented.
- [ ] Work-order relationships are validated.
- [ ] Unknown-reference handling is resolved.

## Acceptance tests

- [ ] AT-19 passes.
- [ ] AT-20 passes.
- [ ] AT-21 passes.

---

# 21. Open Design Decisions and Clarifications

The following details should be confirmed before final implementation. They are not all specified in the approved POC B plan.

| Item | Question / clarification required | Reason |
|---|---|---|
| CRM export location | Confirm the exact bucket name and environment-specific folder configuration | Required for deployment |
| BigQuery dataset configuration | Confirm exact project, dataset, and table names for all environments | Required for loader and dbt configuration |
| IAM | Confirm the Cloud Run service account and its GCS and BigQuery permissions | Required for execution |
| Tokenization | Confirm the existing shared tokenization macro, key storage, and access controls | Required for personal-data protection |
| Account hierarchy | Define behaviour for missing parent accounts or hierarchy loops | Schema document proposes DQ45 |
| Store matching | Define behaviour for multiple active CRM store matches | Schema document proposes DQ46 |
| Work-order references | Resolve the conflict between retaining unknown references and required account relationships | Required for DQ47 and fact integrity |
| Watermark edge cases | Test equal timestamps and late-arriving records | Avoid missing updates |
| Additional schema fields | Confirm proposed `hierarchy_depth`, `tenant_reason`, and `is_open` fields | Not all are approved plan requirements |
| Physical design | Confirm proposed clustering for `fct_work_order` | Schema proposal, beyond the explicit partition requirement |
| Loader metadata | Confirm whether optional load-log fields are needed | Improves operational observability |
| Type-2 history | Decide whether to implement B10 after G7 | Stretch scope |

### Approved versus proposed items

**Approved by the Phase 2 plan:**

- Hourly CRM exports.
- Manifest written last.
- Three CRM source files.
- Cloud Run loader.
- Idempotent loading.
- Load tracking.
- Watermark merge models.
- Change-size guard above 50%.
- Customer type mapping.
- Shared customer macro.
- `dim_account`.
- Tenant assignment using the top-level account.
- `dim_store` enrichment.
- `fct_work_order` partitioned by `opened_date`.
- DQ36, DQ37, DQ40, DQ41, DQ42.
- AT-19, AT-20, AT-21.

**Proposed or requiring confirmation:**

- Specific ID patterns for account, CRM store, and work order.
- `hierarchy_depth` and `tenant_reason`.
- `is_open` in `fct_work_order`.
- Proposed clustering for `fct_work_order`.
- DQ45–DQ47.
- Exact tokenization algorithm and key implementation.
- Exact Cloud Run deployment commands and IAM configuration.
- Exact physical DDL and all environment-specific configuration.

---

# 22. Glossary

| Term | Meaning |
|---|---|
| CRM | Customer Relationship Management system |
| Account | An organization or entity recorded in CRM |
| Customer | An account classified as CUSTOMER and Active |
| Vendor | An account classified as VENDOR |
| Partner | An account classified as PARTNER |
| Prospect | A potential customer classified as PROSPECT |
| Tenant | The top-level customer organization used to isolate data |
| `tenant_id` | Identifier of the top-level CRM account |
| G2 | Operational source system providing store and device information |
| GCS | Google Cloud Storage |
| BigQuery | Google Cloud's analytical data warehouse |
| Cloud Run Job | Managed execution environment for containerized jobs |
| dbt | Data transformation framework |
| Raw layer | Stores source data with minimal transformation |
| Staging layer | Applies typing, cleanup, and privacy transformations |
| Intermediate layer | Applies business logic and incremental transformations |
| Warehouse dimension | Descriptive entity table such as `dim_account` |
| Fact table | Table containing measurable business events or transactions |
| Watermark | A value used to identify records that have changed since the previous processing run |
| Idempotency | Re-running an operation produces no duplicate results |
| Manifest | File containing export metadata, including size and checksum |
| MD5 | Checksum used to validate file integrity |
| DQ | Data-quality check |
| AT | Acceptance test |
| POC | Proof of Concept |

---

# 23. Final Understanding

POC B establishes the customer and tenant foundation for the Store Alert Data Lake.

It starts with CRM exports and creates a controlled ingestion pipeline. The loader validates each export, prevents duplicate loads, tracks failures, and holds unusually large changes for manual approval.

The data is then transformed through staging and intermediate models. Personal contact information is tokenized before leaving staging. A shared customer type mapping and macro ensure that customer classification is consistent.

The resulting `dim_account` becomes the central account definition.

Next, G2 stores are matched with CRM stores, their account relationships are resolved, and the top-level CRM account ID becomes the store's `tenant_id`. The existing `dim_store` from POC C is enriched with tenant and customer-store information.

Finally, CRM work orders are transformed into `fct_work_order`.

The dependency chain is:

```text
CRM export simulator
        |
        v
GCS export folders
        |
        v
poc-crm-loader
        |
        v
raw_crm
        |
        v
stg_crm__*
        |
        v
int_crm__*
        |
        +----------------------+
        |                      |
        v                      v
   dim_account          int_store__tenant
                               ^
                               |
                     raw_g2 + POC C dim_store
                               |
                               v
                         dim_store enriched

int_crm__work_order + int_store__tenant
        |
        v
fct_work_order
```

The outputs then support the rest of Phase 2:

- **POC C** consumes the account, tenant, and work-order models as part of the warehouse transformation layer.
- **POC D** uses customer and tenant information to enforce tenant-level security.
- **POC E** orchestrates and monitors CRM ingestion and transformation.
- **POC F** can use the completed warehouse tables for performance and cost evaluation.

The central principle is:

**CRM defines who the customer is. The top-level CRM account defines the tenant. Every downstream warehouse model and security rule must use those same definitions.**
