# Personal-data inventory (task 0.7 item 6, prepares D9)

Owner: Dev 2. Reviewers: Dev 5 (tokens, C9 and D9), Dev 3 (sources).
Status: DRAFT. Items marked **[confirm]** need agreement before D9 starts (Day 7).

**Personal data** here means any value that identifies a person on its own (direct) or that can be linked back to
one person (indirect). Company names, store names and team names aren't personal data.

Sources checked:
- **G2:** the 9 POC 1 stage models in `data-lake-ETL-tool/app/models/stage/tables/`, plus the two new tables in
  plan section 4.3.
- **CRM:** the export spec (`specs.md` section 1).
- **LPOS:** the case-event Avro schema (plan section 4.3).
- **`sim_g2_datalake`:** the tables in plan section 4.3.

## 1. Policy tags

Taxonomy `poc-pii` in `us-central1` (D-21), with fine-grained access control turned on.

| Tag | Meaning | Fine-grained reader (sees the real value) | Masked reader (if spike 3 says yes) |
|---|---|---|---|
| `pii_direct` | Names, email addresses | `sa-dwh-writer-dev`, `sa-dwh-writer-int` (they tokenise); one named internal person | Internal analyst, `sa-pii-probe`: SHA-256 |
| `pii_indirect` **[confirm]** | Ids that point to one person (user ids) | Same as above | Same as above: SHA-256 |

`pii_indirect` is new; the plan names only `pii_direct`. **Why:** a user id like `U001` is a direct key into
`users`, so anyone who can read both tables can find the person. **If it's turned down:** user ids stay untagged in
raw, and only the tokens in dbt protect them.

## 2. Inventory

### 2.1 G2 (Cloud SQL `g2`, landing in `raw_g2.g2_<table>`)

| # | Column | Kind | Tag in `raw_g2` | What reaches `build` and `wh` | Notes |
|---|---|---|---|---|---|
| G1 | `users.user_name` | Direct: display name | `pii_direct` | Nothing. `dim_user` isn't ported | Generated names are role-style ("Field Specialist 01"), but treat them as real |
| G2 | `users.email` | Direct: email | `pii_direct` | Nothing | `@example.com` in the generator |
| G3 | `users.user_id` | Indirect: user key | `pii_indirect` | Tokens only, through G4 and G5 | |
| G4 | `alert_incidents.assigned_user_id` | Indirect | `pii_indirect` | `fct_alert.assignee_token` (C3) | |
| G5 | `alert_history.changed_by_user_id` | Indirect | `pii_indirect` | **`fct_alert_history.changed_by_token`** **[confirm]** | **Gap in the plan:** Appendix A tokenises the assignee only. This column would reach `wh` as a raw user id, and DQ41's deny list wouldn't catch it |
| G6 | `alert_history.comments` | Free text: may name a person | None **[confirm]** | Published as is in the POC | The generated comments name no one (`COMMENTS` in `generate_synthetic_data.py`). With client data this needs a decision: drop it, tag it or scrub it. DQ41's email scan catches emails in it, but not names |
| G7 | `store_access.principal` | Direct for the two team members' Google accounts; service account emails aren't personal | `pii_direct` | `sec_{env}.map_tenant_access.principal`, **kept in plain text** | **Exception.** The tenant row policy compares this column with `SESSION_USER()`, so it can't be tokenised. Only writers and the row policies read `sec_{env}`. C9's email scan needs an allow-list entry for this column, or AT-28 fails |

Not personal: `users.team_id`, `users.is_active`, `brands.ultimate_parent` (a company), every column of `brands`,
`teams`, `statuses`, `alert_types`, `stores`, `device_locations` and `heartbeat`.

### 2.2 CRM (hourly export, landing in `raw_crm.*_landing`)

| # | Column | Kind | Tag in `raw_crm` | What reaches `build` and `wh` | Notes |
|---|---|---|---|---|---|
| C1 | `account.primary_contact_name` | Direct | `pii_direct` (set in the Terraform schema) | Nothing. Dropped in `stg_crm__account` | |
| C2 | `account.primary_contact_email` | Direct | `pii_direct` | `dim_account.primary_contact_token` | The token is made from the email, so the same person gets the same token across accounts **[confirm with Dev 5]** |

Not personal: `account_name` (a company), and every column of `store.csv` and `work_order.csv`.
**Production note:** in a real CRM, a sole trader's `account_name` is a person's name. Re-check this column against
client data.

### 2.3 LPOS case events (`raw_lpos.case_event`)

| # | Column | Kind | Tag | What reaches `build` and `wh` | Notes |
|---|---|---|---|---|---|
| L1 | `offender_token` | Indirect: opaque id from the source | None | `fct_case`, and `dim_offender` per tenant | Pseudonymous, but still personal data under GDPR-style rules. If LPOS uses one token across tenants, two tenants could link the same person. `dim_offender` is per tenant, which helps. **[confirm]** whether to re-tokenise it with our key and `tenant_id`, so tokens differ per tenant |
| L2 | `attributes` (Pub/Sub metadata) | None by contract | None | Not modelled | The simulator sets no attributes. Add a rule to `specs.md`: publishers put no personal data in attributes |

Not personal: `event_id`, `case_id`, `event_type`, `event_ts`, `g2_store_id`, `case_status`, `loss_amount`,
`items_count`.

### 2.4 `sim_g2_datalake`

No personal data in `wheel`, `wheel_event` or `derived_alert`.

## 3. Where personal data lands apart from the sources

These copies aren't covered by D9 or AT-28 as the plan stands. Each needs an action.

| Where | What | Risk | Proposed action | Owner |
|---|---|---|---|---|
| `raw_g2.g2_users`, `g2_alert_incidents`, `g2_alert_history`, `g2_store_access` | G1–G5, G7 | Datastream creates these tables, so Terraform can't tag them | `scripts/security/tag_raw_columns.py` runs **as soon as the A4 backfill finishes (Day 4)**, not on Day 7 | Dev 2, Dev 5 |
| `raw_g2_parity.*` | Snapshots of the above (A4) | Snapshots are read-only. If taken before tagging, they stay untagged | Take the parity snapshot **after** tagging. Spike 3 step 3f checks whether a snapshot keeps the tags | Dev 2 |
| `poc1_baseline.dim_user`, `bak_dim_user` | `name`, `email` (POC 1 `dim_user`) | Untagged copies, from task 0.3 | Freeze `dim_user` with only `id`, `fk_team` and `is_active`. Parity (C4 step 3) needs only the count of distinct users | Dev 1 |
| `poc_stage_dev.users`, `poc_dwh_dev.dim_user` | POC 1 originals | Untagged, outside Phase 2 | Leave them for now; tag them or delete them at teardown **[confirm]** | Dev 1 |
| `stg_{env}` views over raw | G1–G5, C1–C2 | Low: a view still enforces the base table's column tags for whoever queries it | None. Readers have no access to `stg` anyway | — |
| `dq_{env}` (`store_failures`) | Failing rows of tests on staging models | Tests on `stg_g2__users` or `stg_crm__account` would copy names and emails into untagged tables | No `store_failures` on tests that select tagged columns. Test tokens, not raw values | Dev 1 |
| `sec_{env}.map_tenant_access` | G7 | Plain emails, by design | The exception in G7, plus the allow-list in C9 | Dev 2, Dev 5 |
| `audit_logs` | `principalEmail` of every caller | Team members' emails | Engineers only. Note it in the security report | Dev 2 |
| Cloud SQL `g2` | The source rows | Not BigQuery, so no tags apply | Only `simulator_user` and `datastream_user` can connect | Dev 2 |

## 4. What D9 tags (the list `tag_raw_columns.py` and Terraform use)

| Table | Column | Tag | Set by |
|---|---|---|---|
| `raw_crm.account_landing` | `primary_contact_name`, `primary_contact_email` | `pii_direct` | Terraform (`crm_landing` module) |
| `raw_g2.g2_users` | `user_name`, `email` | `pii_direct` | `tag_raw_columns.py` |
| `raw_g2.g2_users` | `user_id` | `pii_indirect` **[confirm]** | `tag_raw_columns.py` |
| `raw_g2.g2_alert_incidents` | `assigned_user_id` | `pii_indirect` **[confirm]** | `tag_raw_columns.py` |
| `raw_g2.g2_alert_history` | `changed_by_user_id` | `pii_indirect` **[confirm]** | `tag_raw_columns.py` |
| `raw_g2.g2_store_access` | `principal` | `pii_direct` | `tag_raw_columns.py` |

**Side effects of tagging:**
- Every identity that runs dbt over these tables needs fine-grained reader on both tags: the two writers, the CI
  build account, and developers running `--target local`.
- The tokens also need the key, so CI and laptops need a test key (see `access-matrix.md`, section 5).

## 5. Decisions needed

1. Add the `pii_indirect` tag (G3–G5), or rely on tokens alone?
2. Add `changed_by_token` to `fct_alert_history` (G5)? I recommend yes; without it, a raw user id reaches `wh`.
3. `comments` (G6): publish as is for the POC, and record the production decision?
4. Re-tokenise `offender_token` per tenant (L1)?
5. Change the 0.3 baseline so `dim_user` is frozen without names and emails?
6. Move `tag_raw_columns.py` to Day 4, before the parity snapshot?
