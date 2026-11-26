# Spikes

**Owner:** Dev 2 (1-3), Dev 1 (4-5), Dev 4 (6)  
**Tasks:** 0.9

One section per spike question, with evidence. Spikes 1–3 (POC D) are run with the kit in
`scripts/spikes/poc_d/` (see its README). Paste the PASS/FAIL lines and job ids that `run_as.py` prints; they are
the evidence. Spikes 4–6 belong to their owners and are added below by them.

**Spikes 1–3 were run on 2026-11-25** in `gks-datalake-poc2-dev` with the kit (temporary `spike_*` resources,
all deleted afterwards). Job ids below are the evidence.

---

## Spike 1: row-policy subquery for readers who can't read the mapping table

**Question:** can a principal **without** read access to `map_tenant_access` query a table whose row policy has a
subquery on it?

**Answer: NO.** And the plan's fallback (a row policy on the mapping table itself) is **impossible** too.

| Step | Identity | Expected | Result | Job id / note |
|---|---|---|---|---|
| s1a | reader A | only ACC-1001, 40 | **denied**: "User does not have permission to query table spike_rls_sec.map_tenant_access" | 21865d72-5dc3-4ee3-a726-3a4c9fb1cae6 |
| s1a | reader B | only ACC-1002, 20 | denied (same) | a203f0f3-e579-460f-93ec-bab6bbbb6905 |
| s1c | reader A | denied | denied | 07ed06c8-0c35-4f33-be08-97e109239a5b |
| s1f plan fallback: viewer on sec + `principal = SESSION_USER()` policy on the mapping | reader A | s1a works | **400 invalid**: "Tables which have row access policies may not be referenced by other row access policies" | job of s1a after s1f |
| extra: policy reads an authorized view instead of the table | you | policy created | **400 invalid**: "is of type VIEW, which is invalid for use as a reference in a row access policy" | — |
| extra: viewer on sec, **no** policy on the mapping | readers A, B | isolation | A sees ACC-1001 40, B sees ACC-1002 20, A filtered on B: no rows, `S101` only; **but A can read the whole mapping (B's email)** | a32f89d4…, 85ae501a…, 399cfa97…, 4bf05959… |
| extra, **chosen**: same, mapping stores `TO_HEX(SHA256(LOWER(email)))`; policy compares with `SESSION_USER()` hashed | readers A, B | isolation, no emails visible | A 40, B 20, A on B: no rows; reading the mapping shows only hashes and tenant ids | 47b573bd…, e1400984…, 68bc9246… |

**Consequence (applied in the code):**
- Readers get viewer on `sec_{env}` (Terraform `sec_reader`); D5 case 3 no longer expects `sec` denied.
- `map_tenant_access` stores `principal_hash`, never the email; `policies/tenant.sql` compares
  `principal_hash = TO_HEX(SHA256(LOWER(SESSION_USER())))`. DQ41's allow-list is now empty.
- What a reader can still see in `sec_{env}`: hashes and tenant ids (which tenants exist). Unsalted hashes of known
  emails can be checked by guessing; accepted for the POC, noted in the security report.

## Spike 2: DML under row policies

**Question:** can the writer, with an all-rows policy, run `DELETE` and `INSERT` in one transaction on a table with
row policies and `require_partition_filter`?

**Answer: YES.**

| Step | Identity | Expected | Result | Duration / note |
|---|---|---|---|---|
| s2a transaction | writer | ok | ok ("published") | 9.6 s; job 76906a61-a31a-4c44-a24b-4c4528393eaa |
| s2b verify | you | P1 on 03–04, 80 rows, "(v2)", both policies kept | "(v2)" names; `rls_all_rows` and `rls_tenant` still on `fct_alert` | |
| s2c delete without filter | writer | error | error: "Cannot query over table … without a filter over column(s) 'alert_date'" | |
| s2d replace policy | writer | ok | ok ("policy replaced by the writer") | job 91167bb8-2e76-4fd9-a406-1c78e03251a5 |
| s2e reader insert | reader A | denied | denied: "Permission bigquery.tables.updateData denied" | |

**Final `pocDwhWriterRls` permissions:** `bigquery.rowAccessPolicies.create`, `.update`, `.delete`, `.list`, `.get`,
`.getIamPolicy`, `.setIamPolicy` (as in Terraform). `tables.setCategory` is not needed.

**Can the custom role be granted on one dataset, or only on the project?** Proven at project level; a dataset-level
grant was not tested. Terraform's `writer_rls_role_scope` now defaults to `project`.

**Consequence for E5:** none; `publish.py` works as designed.

## Spike 3: data masking on on-demand pricing

**Question:** is BigQuery data masking available to us with on-demand pricing?

**Answer: YES** (the masked-reader grant took about 4 minutes to take effect).

| Step | Identity | Expected | Result | Note |
|---|---|---|---|---|
| s3_setup step 4: data policy created | you | ok | ok (SHA-256 policy on `pii_direct`) | gcloud 588 has no `taxonomies create`; the kit now uses the REST API |
| s3a | you (tag holder) | real values | real values | |
| s3b | masked reader | hashes | hashes (first tries denied, PASS at 12:34, ~4 min after the grant) | |
| s3c | reader A, no tag | denied | denied: "neither fine-grained reader nor masked get permission" | |
| s3d | reader A, untagged columns | ok | ok | |
| s3e | writer, no tag, insert | record | **ok**: inserting into tagged columns needs no tag | job fd89478b-05e1-4605-97b3-20314bf6641c |
| s3f snapshot read | reader A | denied | denied: a snapshot keeps the tags | |

**Consequence (applied):** `enable_masking` defaults to true in `terraform/shared/security.tf`; `sa-pii-probe` and
the internal analyst get masked reader. `sa-crm-loader` and Datastream need no fine-grained reader to write (s3e).
`raw_g2_parity` snapshots keep tags, so the snapshot order doesn't matter.

---

## Spike 4: native materialized views over row-policy tables (Dev 1)

_To be written by Dev 1._ POC D depends on the answer: until it is in, the native views
(`mv_alert_trend_daily`, `mv_cart_count_daily`) must not be tenant-facing.

## Spike 5: `CREATE TABLE ... LIKE` options (Dev 1)

_To be written by Dev 1._

## Spike 6: one transaction over about 20 tables (Dev 4)

_To be written by Dev 4._
