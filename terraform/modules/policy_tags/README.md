# terraform/modules/policy_tags

**Owner:** Dev 5 (Dev 2 reviews)  
**Tasks:** D9

Policy taxonomy and tags on raw personal data; masking if available.

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".

## What it creates

- Taxonomy `poc-pii` (us-central1, fine-grained access control on) with tag `pii_direct`.
- `pii_indirect` only if `enable_pii_indirect` (decision 1 in `pii-inventory.md`).
- Fine-grained reader on the tags for `sa-dwh-writer-dev`, `sa-dwh-writer-int` and `internal_pii_reader`.
- If spike 3 says masking is available (`enable_masking = true`): data policy `pii_direct_sha256` (SHA-256) and
  masked reader for the analyst and `sa-pii-probe`. Otherwise readers without the tag are denied.

## Tagging columns (not done here)

| Table | Columns | Where |
|---|---|---|
| `raw_crm.account_landing` | `primary_contact_name`, `primary_contact_email` | `crm_landing` module (POC B): set `policy_tags = [<output pii_direct_policy_tag>]` in the schema |
| `raw_g2.g2_users`, `g2_store_access` (and `pii_indirect` columns if enabled) | see `pii-inventory.md` section 4 | `scripts/security/tag_raw_columns.py` (Datastream creates these tables) |

After tagging, check that Datastream and `poc-crm-loader` still write (D9 step 4); if not, add their identity to
`fine_grained_readers`.

Called from `terraform/shared/security.tf`. The writers are added once they exist: `writers_exist = true` in `terraform/shared` after `terraform/env` is applied.
