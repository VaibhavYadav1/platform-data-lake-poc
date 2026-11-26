# E10: Lineage and Docs Verification Guide

**Task:** E10  
**Owner:** Dev 4  
**Day:** 10  
**Status:** Written, not yet verified in the cloud (needs a deploy and one micro-batch)

---

## What E10 Does

1. **Enables Data Lineage API** in Terraform → BigQuery jobs automatically record lineage
2. **Creates GCS bucket** for dbt docs → `{project_id}-dbt-docs`
3. **Adds Cloud Build steps** → after the deploy, `docs-<env>` runs `dbt docs generate --static` and `publish-docs-<env>` copies `static_index.html` to `<env>/index.html`, with `manifest.json` beside it
4. **Creates the AT-37 check** → fails unless the lineage chain exists and every model has a description

---

## Manual Verification Steps

### Step 1: Check Lineage in Console

After E10 is applied and at least one dbt run has completed:

1. **Open BigQuery** in GCP Console
2. **Navigate to** `wh_dev.fct_alert` table
3. **Click the "Lineage" tab**
4. **Verify you see:**
   ```
   raw_g2.g2_alert_incidents → build_dev.fct_alert → wh_dev.fct_alert
   ```
   
   Or a similar chain showing source → build → published

**What you're checking:**
- The lineage graph appears (not empty)
- It shows tables from different datasets
- The path goes through `build_dev` to `wh_dev`

**If lineage is empty:**
- The API was just enabled - lineage appears after jobs run
- Run a micro-batch: `gcloud workflows run poc-micro-batch-dev --location=us-central1 --data="{}"`
- Wait 5 minutes and check again

**Console link:**
```
https://console.cloud.google.com/bigquery?project={your-project-id}&p={your-project-id}&d=wh_dev&t=fct_alert&page=table
```

---

### Step 2: Check dbt Docs Are Published

1. **Run the AT-37 test:**
   ```bash
   python scripts/acceptance/at37_lineage_and_docs.py --env dev
   ```

2. **Or check manually:**
   ```bash
   gsutil ls gs://{project_id}-dbt-docs/dev/index.html
   ```

3. **Open the docs:**
   - The test prints a URL like:
     ```
     https://storage.cloud.google.com/{project_id}-dbt-docs/dev/index.html
     ```
   - Open it in your browser (you must be authenticated to GCP)
   
4. **What you should see:**
   - A website with "dbt" branding
   - Left sidebar with model groups: `staging`, `intermediate`, `marts`, etc.
   - Click any model → see its description, columns, tests, SQL

**If the page doesn't load:**
- Check you're logged into a Google account with the Viewer role on the project (that is what lets you open the page)
- Check the bucket exists: `gsutil ls gs://{project_id}-dbt-docs`
- Check the file exists: `gsutil ls gs://{project_id}-dbt-docs/dev/`

---

### Step 3: Check Every Model Has a Description

1. **In the dbt docs website**, click through the models in the left sidebar
2. **For each model**, check:
   - The top section has a **description** (not empty)
   - Every **column** has a description
   
3. **Models to spot-check:**
   - `fct_alert` - should describe what an alert row represents
   - `fct_alert_history` - should describe the history grain
   - `dim_store` - should describe the store dimension
   - `mv_store_health` - should describe the health rollup

**If models are missing descriptions:**
- Fix in the dbt `schema.yml` files
- Merge the fix
- Cloud Build will regenerate and upload the docs

---

## What AT-37 Checks

The acceptance test script checks:

| Check | What it validates | How |
|-------|-------------------|-----|
| 1. API enabled | Data Lineage API is turned on | Service Usage API |
| 2. Lineage chain | `wh_<env>.fct_alert` has `build_<env>` and `raw_g2` upstream | Data Lineage API, followed hop by hop. **Fails** if the chain is missing |
| 3. Docs published | The page exists and is not tiny | `gs://{project}-dbt-docs/{env}/index.html` |
| 4. Descriptions present | Every model has a description | Reads `{env}/manifest.json` beside the page. **Fails** and names each model without one |

**Run it:**
```bash
# For dev
python scripts/acceptance/at37_lineage_and_docs.py --env dev

# For int (once int exists)
python scripts/acceptance/at37_lineage_and_docs.py --env int
```

---

## Troubleshooting

### "Data Lineage API is not enabled"

**Cause:** Terraform hasn't applied yet, or the API enablement is still propagating.

**Fix:**
```bash
cd terraform/shared
terraform apply -target=google_project_service.datalineage
```

Wait 2-3 minutes for the API to become active.

---

### "Docs not found in GCS"

**Cause:** Cloud Build hasn't run yet, or the dbt-docs step was skipped.

**Fix:**
1. Check the bucket exists:
   ```bash
   gsutil ls gs://{project_id}-dbt-docs
   ```
2. If the bucket doesn't exist, apply Terraform:
   ```bash
   cd terraform/shared
   terraform apply -target=google_storage_bucket.dbt_docs
   ```
3. Start the deploy build. The triggers may be disabled (`cloudbuild_triggers_disabled`), so run it by hand:
   ```bash
   gcloud builds triggers run poc-main-deploy --branch=main
   ```
   The docs steps print `SKIPPED` until the dbt project (`dbt/dbt_project.yml`) is merged.
4. Watch the Cloud Build run:
   ```bash
   gcloud builds list --limit=1
   gcloud builds log <build-id>
   ```

---

### "No lineage links found"

**Cause:** Lineage takes time to populate after the API is enabled, or no jobs have run yet.

**Fix:**
1. Run a micro-batch to generate lineage:
   ```bash
   gcloud workflows run poc-micro-batch-dev --location=us-central1
   ```
2. Wait 5-10 minutes
3. Check the console lineage view (Step 1 above)
4. The API query in AT-37 may still return empty - **the console view is the authority**

---

### "403 Forbidden" when opening docs URL

**Cause:** Your Google account can't read the bucket. Anyone with the Viewer role on the project can; the bucket can never be opened to `allUsers` or `allAuthenticatedUsers` (public access prevention is enforced).

**Fix:**
1. Check you're logged into the right Google account
2. For someone without the project Viewer role, add them to `docs_extra_readers` in `terraform/shared/terraform.tfvars`, for example `docs_extra_readers = ["user:name@example.com"]`, and apply

---

## Done When (from E10 task)

AT-37 passes, which means:

- ✓ Lineage for `wh_dev.fct_alert` shows the full path in the console
- ✓ Docs page opens successfully
- ✓ Every model has a description

**Record the evidence:**
1. Screenshot of the lineage view showing the path
2. Screenshot of the docs homepage
3. Screenshot of one model's page showing description and columns
4. AT-37 test output showing PASSED

**Save to:** `docs/poc2/at37-evidence/`

---

## Terraform Apply Commands

The E10 resources are in `terraform/shared/lineage.tf`. Apply the whole stack, as for any change:

```bash
cd terraform/shared
terraform init -reconfigure "-backend-config=backend.hcl"
terraform plan "-var-file=terraform.tfvars" "-out=shared.tfplan"
terraform apply shared.tfplan
```

The plan should show 3 to add: the Data Lineage API, the `<project>-dbt-docs` bucket and the write
permission for `sa-cloudbuild-deploy`. Anything else, such as another resource changing, is not E10.

---

## References

- **Task definition:** `docs/poc2/poc-e-execution-plan.md` section 4, E10
- **Acceptance test:** AT-37 in section 5
- **Console lineage view:** BigQuery → select table → Lineage tab
- **Data Lineage API docs:** https://cloud.google.com/data-catalog/docs/concepts/about-data-lineage
