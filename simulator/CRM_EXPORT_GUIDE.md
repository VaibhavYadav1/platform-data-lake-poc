# CRM Export Simulator Guide (Task B2)

## Overview

The CRM export simulator generates realistic hourly CRM snapshots for testing POC B. It creates:
- **Accounts** with hierarchies (parent_account_id), customer types, and contact information
- **Stores** linked to accounts via g2_store_id  
- **Work Orders** linked to accounts, stores, and devices
- **Manifest** with file checksums (written last to signal completion)

## Quick Start

### Generate Test Exports Locally

```bash
# Navigate to project root
cd platform-data-lake-poc

# Generate 3 hourly exports to local directory
python -m simulator crm-export --local-dir ./test_crm_exports --count 3
```

**Output:**
```
test_crm_exports/
  export_ts=20261120T080000Z/
    account.csv (50 accounts)
    store.csv (100 stores)  
    work_order.csv (50 work orders)
    manifest.json
  export_ts=20261120T090000Z/
    ...
  export_ts=20261120T100000Z/
    ...
```

### Upload Directly to GCS

```bash
# Upload to GCS bucket
python -m simulator crm-export \
  --bucket gks-datalake-poc2-dev-crm \
  --prefix crm \
  --count 3

# Verify upload
gsutil ls gs://gks-datalake-poc2-dev-crm/crm/
```

## Test Scenarios

### Normal Operations

```bash
# Small changes (10% - should LOAD normally)
python -m simulator crm-export \
  --local-dir ./test_exports \
  --count 3 \
  --change-rate 0.10
```

### AT-21: Change-Size Guard Test

```bash
# Large change (>50% - should trigger HELD status)
python -m simulator crm-export \
  --local-dir ./test_exports \
  --count 2 \
  --big-change

# This creates:
# 1. First export: baseline
# 2. Second export: >60% of accounts changed (trips guard)
```

### AT-20: Idempotency Test

```bash
# Generate same export twice
python -m simulator crm-export \
  --local-dir ./test_exports \
  --count 1 \
  --start-time 20261120T080000Z \
  --seed 42

# Generate again with same parameters (same timestamp, same seed)
python -m simulator crm-export \
  --local-dir ./test_exports_2 \
  --count 1 \
  --start-time 20261120T080000Z \
  --seed 42

# Should produce identical files (verify with diff or MD5)
```

### Data Quality Issues

```bash
# Plant DQ issues for testing (DQ36: unknown customer type)
python -m simulator crm-export \
  --local-dir ./test_exports \
  --count 1 \
  --plant-issues
```

## Command Reference

### Required Arguments

**Either** `--bucket` (for GCS) **or** `--local-dir` (for local filesystem)

### Optional Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--prefix` | `crm` | Folder prefix in GCS bucket |
| `--count` | `1` | Number of hourly exports to generate |
| `--change-rate` | `0.1` | Change rate per export (0.0-1.0) |
| `--big-change` | `false` | Force >50% change in last export (AT-21) |
| `--plant-issues` | `false` | Plant data quality issues for testing |
| `--seed` | `42` | Random seed for reproducibility |
| `--start-time` | now | First export timestamp (YYYYMMDDTHHMMSSZ) |

## Data Characteristics

### Accounts (50 by default)
- **60%** are customers (type: 100000000)
- **15%** are vendors (type: 100000001)
- **15%** are partners (type: 100000002)
- **10%** are prospects (type: 100000003)
- **10%** have parent accounts (creates hierarchies)
- All include personal contact information (name, email)

### Stores (100 by default)
- Linked to accounts (multiple stores per account possible)
- Mapped to G2 stores via `g2_store_id` (format: S0001, S0002, ...)
- ~95% Active, ~5% Inactive

### Work Orders (50 initial, grows over time)
- Linked to accounts, stores, and devices
- Types: INSTALL, REPAIR, MAINTENANCE, INSPECTION, UPGRADE
- Statuses: OPEN, IN_PROGRESS, CLOSED, CANCELLED
- ~70% are closed, ~30% are open/in-progress

## Evolution Across Exports

Each export simulates realistic CRM changes:

1. **Account changes** (~10% per export by default)
   - Updated timestamps
   - Occasional status changes (Active ↔ Inactive)
   
2. **Store changes** (~5% per export)
   - Updated timestamps
   - Occasional status changes

3. **Work order evolution**
   - Open work orders may close
   - New work orders created
   - Status transitions

4. **New records**
   - 30% chance of 1-3 new accounts per export
   - 50% chance of 1-5 new work orders per export

## Reproducibility

Using the same `--seed` and `--start-time` produces **identical** exports:

```bash
# Run 1
python -m simulator crm-export \
  --local-dir ./run1 \
  --count 2 \
  --seed 42 \
  --start-time 20261120T080000Z

# Run 2 (should be identical)
python -m simulator crm-export \
  --local-dir ./run2 \
  --count 2 \
  --seed 42 \
  --start-time 20261120T080000Z

# Verify
diff -r ./run1 ./run2  # Should show no differences
```

## CSV Format

All CSV files:
- Use **UTF-8** encoding
- Use **\n** line endings (not \r\n)
- Include headers as first row
- Include `export_ts` column in every row
- Use ISO 8601 timestamps (YYYY-MM-DDTHH:MM:SSZ)

### account.csv Columns
```
account_id,account_name,customer_type_code,status,parent_account_id,
primary_contact_name,primary_contact_email,updated_at,export_ts
```

### store.csv Columns
```
crm_store_id,account_id,g2_store_id,status,updated_at,export_ts
```

### work_order.csv Columns
```
work_order_id,account_id,crm_store_id,g2_device_id,work_type,status,
opened_at,closed_at,updated_at,export_ts
```

## Manifest Format

```json
{
  "export_ts": "20261120T080000Z",
  "files": [
    {
      "name": "account.csv",
      "size": 1234,
      "md5": "abc123..."
    },
    {
      "name": "store.csv",
      "size": 5678,
      "md5": "def456..."
    },
    {
      "name": "work_order.csv",
      "size": 9012,
      "md5": "ghi789..."
    }
  ]
}
```

**Important:** `manifest.json` is **written last** to signal that the export is complete and ready for loading.

## Testing the Simulator

```bash
# Run unit tests
cd platform-data-lake-poc
pytest simulator/tests/test_crm_export.py -v

# Tests cover:
# - State initialization
# - Customer type distribution
# - Account hierarchies
# - Store-account linking
# - Work order references
# - Change rate evolution
# - Big change threshold
# - CSV format correctness
# - Manifest creation
# - Reproducibility
```

## Integration with CRM Loader

After generating exports, test the loader:

```bash
# 1. Generate exports
python -m simulator crm-export \
  --bucket gks-datalake-poc2-dev-crm \
  --prefix crm \
  --count 3

# 2. Run loader
cd loaders/crm
python crm_loader.py \
  --bucket gks-datalake-poc2-dev-crm \
  --prefix crm \
  --project gks-datalake-poc2-dev \
  --dataset raw_crm

# 3. Verify in BigQuery
bq query --use_legacy_sql=false '
SELECT export_folder, status, account_rows, store_rows, work_order_rows
FROM raw_crm.load_log
ORDER BY loaded_at DESC
LIMIT 5
'
```

## Example Workflow

Complete POC B testing workflow:

```bash
# Step 1: Generate baseline + 2 normal changes
python -m simulator crm-export \
  --local-dir ./test_crm \
  --count 3 \
  --change-rate 0.10

# Step 2: Generate big change for guard test
python -m simulator crm-export \
  --local-dir ./test_crm \
  --count 1 \
  --big-change

# Step 3: Upload to GCS
gsutil -m cp -r ./test_crm/* gs://gks-datalake-poc2-dev-crm/crm/

# Step 4: Run loader (will process first 3, hold the 4th)
cd loaders/crm
python crm_loader.py \
  --bucket gks-datalake-poc2-dev-crm \
  --prefix crm \
  --project gks-datalake-poc2-dev \
  --dataset raw_crm

# Step 5: Build dbt models
cd ../../dbt
dbt build --select +fct_work_order +dim_account +dim_store

# Step 6: Run acceptance tests
dbt test --select at19_customer_definition at19_tenants_are_customers
```

## Troubleshooting

**Issue: Import error when running simulator**
```bash
# Make sure you're in the project root
cd platform-data-lake-poc

# Run as module
python -m simulator crm-export --help
```

**Issue: GCS upload fails**
```bash
# Check authentication
gcloud auth application-default login

# Verify bucket exists
gsutil ls gs://gks-datalake-poc2-dev-crm/

# Check permissions
gsutil iam get gs://gks-datalake-poc2-dev-crm/
```

**Issue: Want to regenerate same data**
```bash
# Use same seed and start time
python -m simulator crm-export \
  --local-dir ./exports \
  --seed 42 \
  --start-time 20261120T080000Z \
  --count 3
```

## Implementation Details

### File: `simulator/crm_export.py`

**Key Classes:**
- `CRMState`: Maintains accounts, stores, work orders across exports
- `CRMExportError`: Exception for export generation errors

**Key Functions:**
- `initialize()`: Create initial CRM data
- `evolve()`: Apply changes between exports
- `generate_export()`: Create CSV files for one export
- `write_export_folder()`: Write to local filesystem
- `upload_to_gcs()`: Upload to Google Cloud Storage

### Test Coverage

`simulator/tests/test_crm_export.py` includes 20+ tests covering:
- ✅ State initialization
- ✅ Customer type distribution
- ✅ Hierarchies and relationships
- ✅ Change rate simulation
- ✅ Big change enforcement
- ✅ CSV format validation
- ✅ Manifest creation
- ✅ Reproducibility
- ✅ Data quality issue planting

## See Also

- [POC B Documentation](../docs/GKS-POC-Phase2-POC-B-crm-data-model-and-integration.html)
- [CRM Loader](../loaders/crm/README.md)
- [Simulator README](./README.md)
