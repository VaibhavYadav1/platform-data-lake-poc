# POC D spikes 1–3 (task 0.9, Day 2)

Three questions, half a day or less each. Results go in `docs/poc2/spikes.md`, sections "Spike 1" to
"Spike 3" (the tables are ready to fill in).

| Spike | Question | If the answer is "no" (plan section 5) |
|---|---|---|
| 1 | Can a reader **without** access to `map_tenant_access` query a table whose row policy has a subquery on it? | Readers get viewer on `sec_{env}`, plus a row policy on the mapping table: `principal = SESSION_USER()` (`s1f`) |
| 2 | Can the writer, with an all-rows policy, run `DELETE` and `INSERT` in one transaction on a table with row policies and `require_partition_filter`? | Record the exact error. The E5 publish design changes before Day 6 |
| 3 | Is BigQuery data masking available to us on on-demand pricing? | D9 uses column access control: readers without the tag get an error |

## What gets created

Everything is in `gks-datalake-poc2-dev`, `us-central1`, labelled `purpose=spike`. Tables expire after 3 days.

| Thing | Stands for |
|---|---|
| `spike_rls.fct_alert` (partitioned, filter required, clustered) | A published fact in `wh_{env}` |
| `spike_rls.dim_store` | A published dimension |
| `spike_rls.*_build` | What dbt hands to publish |
| `spike_rls_sec.map_tenant_access` | `sec_{env}.map_tenant_access` |
| `spike_rls.account_contact` (tagged columns) | `raw_crm.account_landing` |
| `spike-reader-a`, `spike-reader-b` | Tenant A and B readers (dataset viewer + job user) |
| `spike-writer` + custom role `spikeRlsWriter` | `sa-dwh-writer-dev` + `pocDwhWriterRls` |
| `spike-masked` | `sa-pii-probe`: viewer and masked reader, no tag |

Test data follows `specs.md` section 3: `ACC-1001` tenant A has 40 alerts, `ACC-1002` tenant B has 20,
`ACC-2001` (vendor) has 10, and a NULL tenant has 10. That's 80 rows over 2026-11-01 to 2026-11-10.

## Before you start

- **Your account** needs to be able to:
  - create service accounts and custom roles;
  - set project IAM;
  - enable APIs;
  - create Data Catalog taxonomies.

  Project Owner is enough. Without it, ask whoever administers the sandbox to run `00_setup.sh`.
- **Tools:** `gcloud`, `bq`, `curl`, Python 3.10+, and `pip install google-cloud-bigquery google-auth`.
- **Logins:** `gcloud auth login` and `gcloud auth application-default login`. `run_as.py` uses the application
  default credentials.
- **Settings:** set `ME` in `spike.env`.
- **Delays:** new IAM grants can take a few minutes. If an impersonated query fails at first with
  `iam.serviceAccounts.getAccessToken`, wait and retry.

## Run order

From this folder, in Git Bash:

```bash
set -a; source spike.env; set +a
bash 00_setup.sh                          # service accounts, role, datasets, data, policies (~5 min)
```

### Spike 1: policy subquery for readers who can't read the mapping (~1 hour)

```bash
python run_as.py spike1/s1a_count_own.sql      --as $SA_READER_A --expect ok      # only ACC-1001, 40
python run_as.py spike1/s1a_count_own.sql      --as $SA_READER_B --expect ok      # only ACC-1002, 20
python run_as.py spike1/s1b_other_tenant.sql   --as $SA_READER_A --expect ok      # (no rows)
python run_as.py spike1/s1c_mapping_direct.sql --as $SA_READER_A --expect denied
python run_as.py spike1/s1d_dim_and_join.sql   --as $SA_READER_A --expect ok      # S101 only
python run_as.py spike1/s1e_revoke.sql                                            # as you
python run_as.py spike1/s1a_count_own.sql      --as $SA_READER_A --expect ok      # (no rows) now
python run_as.py spike1/s1e_grant.sql                                             # as you; restore
```

- **If `s1a` is refused:** the answer is **no**.
  1. Run `python run_as.py spike1/s1f_fallback_setup.sql` as yourself.
  2. Re-run `s1a`, which should now work.
  3. Re-run `s1c` with `--expect ok`. It should show reader A's own row only.
- **Either way:** confirm that reader A never sees `ACC-2001` or NULL-tenant rows.

### Spike 2: DML under row policies (~1 hour)

```bash
python run_as.py spike2/s2a_publish_txn.sql --as $SA_WRITER --expect ok --param dates=DATE[]:2026-11-03,2026-11-04
python run_as.py spike2/s2b_verify.sql                                            # as you: P1 on 03-04, 80 rows, "(v2)"
bq ls --row_access_policies $PROJECT:spike_rls.fct_alert                          # both policies still there
python run_as.py spike2/s2c_no_partition_filter.sql   --as $SA_WRITER   --expect error
python run_as.py spike2/s2d_writer_replaces_policy.sql --as $SA_WRITER  --expect ok
python run_as.py spike2/s2e_reader_dml.sql            --as $SA_READER_A --expect denied
```

- Write down the `s2a` duration. Spike 6 (Dev 4) times the same thing over about 20 tables.
- **Optional `s2f`:** what happens to a publish if the writer is missing from `rls_all_rows`. The steps are in the
  file.
- **If `s2d` is denied:** the custom role is missing a permission. Add the permission named in the error to
  `00_setup.sh` (`PERMS`), re-run it, and record the final list for D2.

### Spike 3: masking (~1 hour)

```bash
bash spike3/s3_setup.sh                       # step 4's output IS the main answer
python run_as.py spike3/s3a_tag_holder.sql                                   --expect ok      # real values
python run_as.py spike3/s3b_masked_reader.sql   --as $SA_MASKED   --expect ok      # hashes (or denied if no masking)
python run_as.py spike3/s3c_no_tag_reader.sql   --as $SA_READER_A --expect denied
python run_as.py spike3/s3d_untagged_columns.sql --as $SA_READER_A --expect ok
python run_as.py spike3/s3e_writer_insert.sql   --as $SA_WRITER                    # record ok or denied
python run_as.py spike3/s3f_snapshot.sql                                           # as you
python run_as.py spike3/s3f_snapshot_read.sql   --as $SA_READER_A --expect denied  # do snapshots keep tags?
```

### Clean up

```bash
bash 99_teardown.sh
```

## What each result means for the plan

| Result | Consequence |
|---|---|
| Spike 1 yes | Readers get no access to `sec_{env}`. D5 case 3 adds `sec_{env}`, expecting denied |
| Spike 1 no | Readers get viewer on `sec_{env}`. `tables.yaml` gives `map_tenant_access` its own policies. Update the access matrix |
| Spike 2 yes | E5 as designed. The `s2d` permission list becomes `pocDwhWriterRls` |
| Spike 2 no | Record the error and tell Dev 4 the same day: the E5 design changes before Day 6 |
| `s2f` shows wrong rows | Strengthens the rule: `publish.py` step 5 must check the writer is in `rls_all_rows` before publishing |
| Spike 3 yes | D9 creates the masking policy; the internal analyst and `sa-pii-probe` get masked reader |
| Spike 3 no | D9 and AT-28 rely on "denied without the tag" (`s3c`) |
| `s3e` denied | `sa-crm-loader` and the Datastream agent need fine-grained reader (D9 step 4) |
| `s3f` returns real values | `raw_g2_parity` must be snapshotted after tagging (`pii-inventory.md` section 3) |
