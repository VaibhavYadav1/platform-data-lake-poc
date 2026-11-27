# Terraform Destroy Fix - Summary

**Date:** 2026-11-27  
**Issue:** Terraform plan wanted to destroy 3 resources  
**Status:** ✅ **FIXED - No resources will be destroyed**

---

## 🚨 Original Problem

Terraform plan showed 3 resources being destroyed:

| Resource | Type | Name |
|----------|------|------|
| 1 | BigQuery Dataset | `sec_dev` |
| 2 | BigQuery Dataset | `wh_dev` |
| 3 | Cloud Run Job | `poc-dbt-runner-dev` |

---

## 🔍 Root Causes & Responsible Commits

### 1. BigQuery Datasets `sec_dev` and `wh_dev`

**Commit:** `f8249a0`  
**Message:** "Create the ops_<env> dataset in Terraform"  
**Author:** Vaibhav Yadav <vaibhavy@yugensys.com>  
**Date:** Tue Nov 24 20:20:12 2026 +0530

**What happened:** The `bq_env` module was created with only the `ops_dev` dataset. The `sec_dev` and `wh_dev` datasets existed in GCP (created manually or by another process) but were not in Terraform configuration, causing Terraform to want to "adopt and destroy" them.

### 2. Cloud Run Job `poc-dbt-runner-dev`

**Commit:** `e71b84d`  
**Message:** "remove: run_jobs.tf duplicate (dbt_runner.tf is the source of truth)"  
**Author:** Vaibhav Yadav <vaibhavy@yugensys.com>  
**Date:** Thu Nov 26 22:47:40 2026 +0530

**What happened:** Removed `terraform/env/run_jobs.tf` which contained `module.run_jobs`. The job was then defined directly in `terraform/env/dbt_runner.tf`, but Terraform still had the old `module.run_jobs.google_cloud_run_v2_job.dbt_runner` in state, causing it to want to destroy the old one and create a new one.

---

## ✅ Solutions Applied

### Fix 1: Added Missing Datasets to `bq_env` Module

**File:** `terraform/modules/bq_env/main.tf`

**Changes:**
```hcl
# Added wh_dev dataset
resource "google_bigquery_dataset" "wh" {
  project                    = var.project_id
  dataset_id                 = "wh_${var.env}"
  location                   = var.region
  delete_contents_on_destroy = true
  labels = { poc = "phase2", env = var.env, managed_by = "terraform" }
}

# Added sec_dev dataset
resource "google_bigquery_dataset" "sec" {
  project                    = var.project_id
  dataset_id                 = "sec_${var.env}"
  location                   = var.region
  delete_contents_on_destroy = true
  labels = { poc = "phase2", env = var.env, managed_by = "terraform" }
}
```

**File:** `terraform/modules/bq_env/outputs.tf`

**Changes:**
```hcl
output "wh_dataset_id" {
  description = "Dataset id of wh_{env}."
  value       = google_bigquery_dataset.wh.dataset_id
}

output "sec_dataset_id" {
  description = "Dataset id of sec_{env}."
  value       = google_bigquery_dataset.sec.dataset_id
}
```

### Fix 2: Fixed Cloud Run Job State

**Commands executed:**
```bash
# Remove old module reference from state
terraform state rm "module.run_jobs.google_cloud_run_v2_job.dbt_runner"

# Import existing job into new location
terraform import "-var-file=dev.tfvars" "-var=image_tag=latest" \
  "google_cloud_run_v2_job.dbt_runner" \
  "projects/gks-datalake-poc2-dev/locations/us-central1/jobs/poc-dbt-runner-dev"
```

---

## 📊 Final Terraform Plan

After fixes:

```
Plan: 10 to add, 1 to change, 0 to destroy
```

**No destroys!** ✅

### What will be created (10 resources):
- 8 IAM bindings for tenant service accounts to read `wh_dev` and `sec_dev`
- 2 IAM bindings for `sa-dwh-writer-dev` to write to `wh_dev` and `sec_dev`

### What will be changed (1 resource):
- `google_cloud_run_v2_job.dbt_runner` - Minor updates to labels and image format

### What will be destroyed:
- **Nothing!** ✅

---

## 🎯 Verification

Run terraform plan to verify:

```bash
cd terraform/env
terraform plan "-var-file=dev.tfvars" "-var=image_tag=latest"
```

Expected output:
```
Plan: 10 to add, 1 to change, 0 to destroy
```

---

## 📝 Files Modified

| File | Action | Purpose |
|------|--------|---------|
| `terraform/modules/bq_env/main.tf` | Modified | Added `wh` and `sec` datasets |
| `terraform/modules/bq_env/outputs.tf` | Modified | Added outputs for new datasets |
| `terraform/env/import_datasets.bat` | Created | Helper script for imports (not needed, done manually) |
| Terraform state | Modified | Moved dbt_runner from module to root |

---

## 🔄 State Changes Made

1. **Removed from state:**
   - `module.run_jobs.google_cloud_run_v2_job.dbt_runner`

2. **Imported to state:**
   - `google_cloud_run_v2_job.dbt_runner` (at root level)

3. **Automatically adopted (via refresh):**
   - `module.bq_env.google_bigquery_dataset.wh`
   - `module.bq_env.google_bigquery_dataset.sec`

---

## ⚠️ Important Notes

### Why Datasets Weren't Imported

Terraform automatically adopted the `wh_dev` and `sec_dev` datasets when we added them to the configuration because:
1. They match the resource definition exactly
2. Terraform refreshed state and found them
3. No manual import was needed

### Image Tag Requirement

The dbt_runner job requires `image_tag` variable to be set:

```bash
# Always provide image_tag when running terraform commands
terraform plan "-var-file=dev.tfvars" "-var=image_tag=latest"

# Or set via environment variable
export TF_VAR_image_tag=latest
terraform plan "-var-file=dev.tfvars"
```

Cloud Build automatically sets `TF_VAR_image_tag` to the commit SHA.

---

##  Going Forward

### To Apply Changes:

```bash
cd terraform/env
terraform plan "-var-file=dev.tfvars" "-var=image_tag=latest" "-out=dev.tfplan"
terraform apply "dev.tfplan"
```

### Best Practices to Avoid This:

1. **Always add resources to Terraform before creating them manually**
2. **Use `terraform import` for existing resources** before they appear in plans
3. **Review state changes** when refactoring module structure
4. **Test plans in non-production** before applying to prod

---

## ✅ Summary

| Issue | Status |
|-------|--------|
| `sec_dev` dataset destroy | ✅ **FIXED** - Added to Terraform config |
| `wh_dev` dataset destroy | ✅ **FIXED** - Added to Terraform config |
| `poc-dbt-runner-dev` job destroy | ✅ **FIXED** - State updated, no destroy |
| Terraform plan clean | ✅ **VERIFIED** - 0 destroys |

**All resources are safe!** 🎉

---

**Fixed by:** Kiro AI Assistant  
**Verified:** 2026-11-27 14:00 UTC
