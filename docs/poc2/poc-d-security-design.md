# POC D: Tenant security design

| | |
|---|---|
| **Owner** | Shreyash (POC D owner). Under the revised assignment, the POC D owner finishes every POC D task, D1–D10, including the tenant rules (D3), the policy tags (D9) and Looker Studio (D10) |
| **Status** | Draft for review |
| **Sources** | `GKS-POC-Phase2-detailed-plan.md` v2.0: sections 4.2, 4.4, 9 and 12; decisions D-23, D-27, D-28, D-29. The POC B schema reference (`POC_B_Proposed_Scema.html`) |
| **Proves** | AT-24 (isolation), AT-25 (access removal), AT-27 (read-only, with audit evidence), AT-28 (no personal data) |

This note covers two things:

1. Where tenant-level security has to be applied in the pipeline and the BigQuery warehouse.
2. How each control will be built and tested:
   - row-level security (RLS);
   - column-level security (CLS) and tokens;
   - IAM;
   - read-only access;
   - tenant isolation testing.

---

## 1. Where security applies

### 1.1 Pipeline and enforcement points

```
SOURCES (simulated)            LANDING (shared)             PER ENVIRONMENT (dev, int)                          READERS
G2 Cloud SQL ──Datastream──►  raw_g2  [P1 tags on g2_users]
CRM CSV export ──loader────►  raw_crm [P1 tags on contacts] ─► stg_{env} ─► prep_{env} ─► build_{env} ─publish.py─► wh_{env}  [P4 RLS] ─► CLI / test app / Looker Studio
LPOS Pub/Sub ──subscription►  raw_lpos                         [P2 tokens]              (dbt tests)   (one txn)    sec_{env} [P3 mapping]      [P5 read-only IAM]
sim_g2_datalake ────────────►                                                                                     audit_logs [P6 evidence]
                                                    keys.token_key [P2 key, writer only]
```

| # | Enforcement point | What could go wrong | Control | Task |
|---|---|---|---|---|
| P1 | `raw_g2.g2_users`, `raw_crm` contact columns | Raw names and emails are readable | Policy tag `pii_direct`; masking if available | D9 |
| P2 | dbt staging (`stg_crm__account`, `stg_g2__users`, assignee ids) | Personal data reaches `build` or `wh` | `tokenize()` with the key in `keys.token_key`; raw columns dropped in staging; DQ41 | C9 |
| P3 | `sec_{env}.map_tenant_access` | A wrong or leaked principal-to-tenant mapping | Built from G2 `store_access` and `dim_account`; customer tenants only; hidden from readers | D3 |
| P4 | Every tenant-scoped table in `wh_{env}` | Tenant A reads tenant B's rows | Two row access policies, owned and re-applied by `publish.py` | D4, E5 |
| P5 | Reader identities | Writes, DDL, reading upstream data, impersonating the writer | Viewer on `wh_{env}` plus job user only; no token creator on the writer | D2 |
| P6 | `audit_logs` | No proof that the controls held | Log sink, plus evidence queries | D8 |

**Rule:** tenants only ever reach `wh_{env}`. Every other dataset is for the pipeline or engineers only.

### 1.2 How the tenant is derived (from the POC B schema)

```
G2 store_id ─► CRM store.g2_store_id (active record) ─► CRM store.account_id ─► follow parent_account_id ─► root account = tenant_id
```

- `tenant_id` is the **top-level CRM account id** (D-23). `int_store__tenant` (B7) sets it on `dim_store`.
- The fact tables take `tenant_id` from their store.
- **A G2 store with no CRM record:** `tenant_id` is NULL and `is_customer_store` is false (DQ37). No tenant policy matches NULL, so only internal users see it.
- **A store of a non-customer account** (a vendor, say): it keeps its tenant id, but `map_tenant_access` never maps a principal to a non-customer, so no tenant sees it.

### 1.3 Tables in `wh_{env}` and their protection

| Table | `tenant_id` | Row policies | Notes |
|---|---|---|---|
| `fct_alert`, `fct_alert_history` | Yes | Both | Partition filter required; clustered on `tenant_id` first |
| `fct_case`, `fct_wheel_event`, `fct_work_order` | Yes | Both | |
| `dim_store`, `dim_device`, `dim_wheel` | Yes | Both | |
| `dim_account` | Yes | Both | Tenants see only their own account rows. q7 coverage is internal-only |
| `dim_offender` | Yes | Both | Per (`tenant_id`, `offender_token`), so a token can't be matched across tenants |
| `mv_store_health`, `mv_*` dbt marts | Yes | Both | |
| `mv_cart_count_daily`, `mv_alert_trend_daily` (native views) | Yes | **Spike 4** | If row policies on base tables block native views, the views are internal-only |
| `dim_date`, `dim_alert_type`, status seed | No | None | Not tenant data; every reader can read them |
| `sec_{env}.map_tenant_access` | Yes | Spike 1 fallback only | Readers don't get access unless spike 1 fails |
| `scale.*` (F2) | Yes | Both | Same policies over `scale.map_tenant_access` |

---

## 2. Row-level security

**Goal:** each tenant identity sees all of its own rows, and none of another tenant's, in every tenant-scoped table.

### 2.1 Mapping table (D3)

1. **Source:** G2 `store_access(principal, crm_account_id)`. The simulator seeds it and changes it with `revoke` and `grant`.
2. **Model:** `models/security/map_tenant_access.sql`. dbt builds it in `build_{env}`, and `publish.py` publishes it to `sec_{env}` in the same transaction as `wh_{env}`. The plan's version:

   ```sql
   select distinct a.principal, t.tenant_id
   from {{ ref('stg_g2__store_access') }} a
   join {{ ref('dim_account') }} t on t.account_id = a.crm_account_id
   where not a.is_deleted and t.is_customer
   ```

3. **Proposed fix:** the plan's model checks `is_customer` on the account named in `store_access`, which may be a child account. The check should be on the tenant, meaning the root account. Join a second time to `dim_account` on `tenant_id` and require that the root `is_customer`. AT-19 check 2 ("every tenant in `map_tenant_access` is a customer") tests exactly this.
4. **Principals** are full emails, as `SESSION_USER()` returns them. Service accounts appear as `name@project.iam.gserviceaccount.com`.

### 2.2 Policies (D4)

The SQL lives in `orchestration/publish/policies/`. The grantee lists come from `config.<env>.yaml`.

```sql
CREATE ROW ACCESS POLICY IF NOT EXISTS rls_all_rows ON `{project}.wh_{env}.{table}`
GRANT TO ({all_rows_principals})        -- sa-dwh-writer-{env}, internal analyst
FILTER USING (TRUE);

CREATE ROW ACCESS POLICY IF NOT EXISTS rls_tenant ON `{project}.wh_{env}.{table}`
GRANT TO ({tenant_principals})          -- sa-tenant-a/b-user, sa-app-tenant-a/b, the two Looker Studio users
FILTER USING (tenant_id IN (
  SELECT tenant_id FROM `{project}.sec_{env}.map_tenant_access` WHERE principal = SESSION_USER()));
```

### 2.3 How it behaves

| Situation | Result |
|---|---|
| A principal is in `rls_tenant` but has no mapping row | Zero rows |
| A principal is named in no policy | Zero rows. **The writer must be in `rls_all_rows`**, or its own reads, checks and fingerprints return nothing |
| A row has `tenant_id IS NULL` | Hidden from every tenant; visible to all-rows principals |
| Access is revoked (`store_access` row deleted) | Rows disappear after the next micro-batch publishes the mapping. The policies don't change. The target is within one cycle, 20 minutes (AT-25) |
| A new tenant principal is added | The policy SQL changes, so `publish.py` notices the changed hash in `ops_{env}.publish_policy_state` and runs `CREATE OR REPLACE`. A Google group would avoid this |

### 2.4 Ownership and lifecycle (D-28)

- **Until E5 (`publish.py`) is ready:** I apply the policies to `wh_dev` by hand.
- **After that,** `publish.py` step 3 applies them on every publish, and step 5 checks that both exist on every tenant-scoped table.
- Published tables are never recreated, so their policies don't disappear.

### 2.5 Spike dependencies (D1)

| Spike | If yes | If no |
|---|---|---|
| 1: the subquery works for readers who can't read the mapping table | Readers get nothing on `sec_{env}` | Readers get viewer on `sec_{env}`, plus a policy on `map_tenant_access`: `principal = SESSION_USER()` |
| 2: DML works under row policies | E5 as designed | The publish design changes before E5 is built (tell the POC E owner) |
| 4 (POC C owner): native views work over row policies | The views are tenant-facing | The views are internal-only |

---

## 3. Column-level security and personal data

**Goal:** no name or email in `build` or `wh`; people appear only as tokens. Raw personal data is masked, or blocked by policy tags.

### 3.1 Inventory (summary; full list in `pii-inventory.md`)

| Source | Column | Raw (`raw_*`) | Warehouse |
|---|---|---|---|
| G2 `users` | `user_name`, `email` | Tag `pii_direct` (`raw_g2.g2_users`) | Dropped; `dim_user` isn't ported |
| G2 `alert_incidents` | `assigned_user_id` | No tag | `assignee_token` on `fct_alert` |
| G2 `alert_history` | `changed_by_user_id` | No tag | **Gap: the plan doesn't say.** Proposed: tokenise it as `changed_by_token` |
| G2 `alert_history` | `comments` (free text) | Open decision | Covered by the daily email scan |
| G2 `store_access` | `principal` (email) | No tag; RLS needs it in plain text | Stays in `sec_{env}` only. Needs an allow-list entry in the C9 scan |
| CRM `account` | `primary_contact_name`, `primary_contact_email` | Tag `pii_direct` (`raw_crm.account_landing`) | `primary_contact_token` on `dim_account` |
| LPOS `case_event` | `offender_token` | Already opaque | `dim_offender`, per tenant |

### 3.2 Tags and masking (D9; POC D owner)

1. **Taxonomy:** `poc-pii` in `us-central1`, with the tag `pii_direct`.
2. **Fine-grained reader:**
   - `sa-dwh-writer-dev` and `sa-dwh-writer-int`, because they tokenise;
   - one internal person, for the test.
3. **Tagging:**
   - `raw_crm`: through Terraform, on the schema.
   - `raw_g2.g2_users`: Datastream creates that table, so `scripts/security/tag_raw_columns.py` tags it.
4. **Masking, decided by spike 3:**
   - **If available:** a SHA-256 data policy, with masked reader for the internal analyst.
   - **If not:** readers without the tag are denied.
5. **Check:** after tagging, confirm that Datastream and `poc-crm-loader` still write. If either fails, give it fine-grained reader.

### 3.3 Tokens (C9; POC C owner. A dependency of POC D, not a POC D task)

- `tokenize()` is a keyed SHA-256.
- The key sits in `keys.token_key`, which only the writers can read. It's loaded once by a load job, so the key never appears in query text.
- **DQ41** fails the build on a column name from the deny list. The daily full load also scans for values that look like emails.
- **Open:** CI and `--target local` can't read `keys.token_key`. They need a test key, or a stub `tokenize()`.

---

## 4. IAM

**Goal:** least privilege, one identity per job, all in Terraform (`modules/service_accounts`, D2).

### 4.1 Dataset access (plan section 4.4)

R = viewer, W = editor.

| Identity | `raw_*` | `sim_g2_datalake` | `keys` | `stg`/`prep`/`build`/`dq`/`ops` | `sec_{env}` | `wh_{env}` | `audit_logs` | Project |
|---|---|---|---|---|---|---|---|---|
| Datastream service agent | W `raw_g2` | – | – | – | – | – | – | – |
| Pub/Sub service agent | W `raw_lpos` | – | – | – | – | – | – | – |
| `sa-crm-loader` | W `raw_crm` | – | – | – | – | – | – | Job user; CRM bucket viewer |
| `sa-simulator` | – | W | – | – | – | – | – | Cloud SQL client; Pub/Sub publisher; bucket creator |
| `sa-dwh-writer-{env}` | R | R | R | W | W | W + `pocDwhWriterRls`; in `rls_all_rows` | – | Job user; fine-grained reader |
| `sa-orchestrator` | – | – | – | W `ops` | – | – | – | Run invoker; Workflows invoker; night-off rights |
| `sa-tenant-a-user`, `sa-tenant-b-user` | – | – | – | – | – | R; in `rls_tenant` | – | Job user |
| `sa-test-app` | – | – | – | – | – | – | – | Token creator on `sa-app-tenant-a/b` **only** |
| `sa-app-tenant-a`, `sa-app-tenant-b` | – | – | – | – | – | R; in `rls_tenant` | – | Job user |
| Internal analyst | – | – | – | – | – | R; in `rls_all_rows` | – | Job user; masked reader (if spike 3 says yes) |
| Two Looker Studio users | – | – | – | – | – | R `wh_dev`; in `rls_tenant` | – | Job user. Removed after the D10 check |
| Cloud Build service account | – | – | – | W `dbt_pr_*` | – | – | – | Terraform plan and apply |
| Log sink writer identity | – | – | – | – | – | – | W | – |
| **Proposed:** `sa-pii-probe` | R `raw_crm` | – | – | – | – | – | – | Job user; **no** tag |
| **Proposed:** security-suite runner (CI or developer) | – | – | – | W `ops` (results) | – | – | – | Token creator on the test readers, `sa-app-*` and `sa-pii-probe`; **not** on the writer |

### 4.2 Writer's custom role `pocDwhWriterRls`

- **The plan's list:** `bigquery.rowAccessPolicies.create`, `.update`, `.delete`, `.list`, `.getIamPolicy`, `.setIamPolicy`, plus `bigquery.tables.setCategory`.
- **Proposed changes:**
  - add `.get`;
  - drop `tables.setCategory`, which is for setting policy tags, not row policies.
- Spike 2 (`s2d`) confirms the final list.

### 4.3 Gaps to raise with the POC E owner

- **`sa-orchestrator`:**
  - the plan doesn't give it job user, which the watchdog's query needs;
  - nor read access on `raw_g2` and `raw_lpos`, which the watchdog reads.
- **`sa-dwh-writer-{env}`:** it needs write access on the dbt artifacts bucket.

---

## 5. Read-only access

**Goal:** no reader can change anything, whatever path it uses.

1. **Grants:** readers get only BigQuery Data Viewer on `wh_{env}` and job user on the project.
   - No project-level data roles.
   - No editor, owner or admin role anywhere.
   - No access to `raw_*`, `stg`, `prep`, `build`, `dq`, `ops`, `keys` or `sec_{env}`.
2. **No route to the writer:** no reader has token creator or service-account user on `sa-dwh-writer-{env}`. `sa-test-app` can impersonate only the two `sa-app-tenant-*` accounts.
3. **Test application (D7):** `python -m tenant_reader --tenant A --query store_health`.
   - It impersonates the tenant's account and runs parameterised queries with `maximum_bytes_billed`.
   - Its queries can't write, because the impersonated account can't.
4. **Looker Studio (D10):** the report's data credentials are set to **Viewer**, so each viewer's own identity runs the queries and the row policies apply.
5. **Proof:** the security suite (cases 2–4 below) tries every write and every escalation and expects denied. D8 finds each attempt in the audit logs.

---

## 6. Tenant isolation testing

### 6.1 Test data (from `specs.md`, checked against the generator)

| Group | Account | Stores | Who sees it |
|---|---|---|---|
| Tenant A | `ACC-1001` (root; B01 and B02 brands) | Alpha stores | `sa-tenant-a-user`, `sa-app-tenant-a`, Looker user A |
| Tenant B | `ACC-1002` (root; B03) | Beta stores | `sa-tenant-b-user`, `sa-app-tenant-b`, Looker user B |
| Vendor | `ACC-2001` | S137, S138 (B8: two stores) | No tenant (`is_customer` false) |
| No CRM record | – | S136, S140 | No tenant (`tenant_id` NULL, DQ37) |
| Probe store | – | `S-PROBE` | Internal only (AT-16) |

**Proposed additions:**
- `store_access` rows that point at a vendor account and an inactive account. These prove the mapping drops them.
- A **child account under `ACC-1001`**. This proves the root-account rule.
- A **vendor child under a customer parent**. Today its stores would inherit the customer's `tenant_id`, so the customer would see the vendor's stores. B7 and D3 must decide this.

### 6.2 Security suite `scripts/security/test_access.py` (D5)

The suite runs in pytest. It impersonates each identity with `google.auth.impersonated_credentials` and writes its results to `ops_{env}.security_test_result`.

| # | Case | Identity | Expected | AT |
|---|---|---|---|---|
| 1 | For each tenant-scoped table: total rows, and rows with another tenant's id | Each tenant identity | Total = the internal count for that tenant; others = 0 | AT-24 |
| 2 | `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`/`DROP`/`ALTER TABLE` in `wh` | Each reader | Denied | AT-27 |
| 3 | `SELECT` from `raw_*`, `stg`, `prep`, `build`, `dq`, `ops`, `keys` (plus `sec` if spike 1 says yes) | Each reader | Denied | AT-27 |
| 4 | Impersonate `sa-dwh-writer-{env}` | Each reader, and `sa-test-app` | Permission denied | AT-27 |
| 5 | `SELECT primary_contact_email FROM raw_crm.account_landing` | **`sa-pii-probe`** (the plan says the analyst, who can't read `raw_crm`, so the test would pass without checking tags) | Masked, or denied by the tag | AT-28 |
| 6 | NULL-tenant stores, vendor stores, `S-PROBE` | Each tenant identity | Not visible | AT-24 |
| 7 | Query repeatedly during a publish | Tenant identity | Old version, then new. Never a mix | AT-29 |

### 6.3 The other tests

| Test | Steps | Pass |
|---|---|---|
| **D6, access removal (AT-25)** | Count tenant A rows. Run `simulator revoke`. Poll every minute. Then run `simulator grant` | 0 rows within 20 minutes; rows come back after the grant |
| **D7, test app (AT-24)** | Run `tenant_reader` for A and B. Run A with a filter on B's id. Try to impersonate the writer | Different rows; 0 rows; refused |
| **D10, Looker Studio (AT-24)** | The same report opened by user A, user B and the analyst | Different rows. Screenshots go in the security report |
| **D8, evidence (AT-27)** | For every blocked attempt: its log entry in `audit_logs`, and its `JOBS_BY_PROJECT` row with `accessDenied` | Each attempt is linked in `security-report.md` |
| **Second environment (AT-31)** | Run the tenant cases in `int` | Green |

---

## 7. Order of work (POC D owner: all D tasks)

The plan's day-by-day developer schedule (section 14.2) no longer applies. Each POC owner finishes their own POC's
tasks. The order below follows dependencies only; a task starts when what it needs is ready.

| Step | Task | Can start when | Blocked by another POC? |
|---|---|---|---|
| 1 | D1: spikes 1–3 | Now | No |
| 2 | D2: identities and IAM in Terraform, the audit sink, the access matrix in `security-report.md` | Terraform skeleton exists (0.2) | POC E / foundation |
| 3 | D9: taxonomy and tags. `raw_crm` tags first; `raw_g2.g2_users` after Datastream | D1 spike 3 answered; `raw_crm` (B3) and `raw_g2` (A4) exist | POC A, POC B |
| 4 | D3: tenant rules, `store_access` test rows, `map_tenant_access` | `dim_account` (B6) and `stg_g2__store_access` (A10) exist | POC A, POC B |
| 5 | D4: row policies on `wh_dev`, by hand until `publish.py` applies them | D3 done; `wh_dev` tables exist | POC C, POC E |
| 6 | D5: security suite | D4 done | No |
| 7 | D7: test app | D2 and D4 done | No |
| 8 | D6: access-removal test | D5 done; micro-batch running (E4) | POC E |
| 9 | D8: evidence queries and security report | D5 run with the sink in place | No |
| 10 | D10: Looker Studio tenant check | The report exists (F5) | POC F |

**Can run in parallel, with nothing outside POC D blocking them:** D1, D2, and the D5 and D7 code (written against
the spike datasets before `wh_dev` exists).

---

## 8. Issues to settle

| # | Issue | Proposal |
|---|---|---|
| 1 | D5 case 5 tests nothing: the analyst can't read `raw_crm` | Add `sa-pii-probe` |
| 2 | The plan creates the audit sink in D8, after the first D5 runs, so those runs leave no evidence | Create the sink in D2; keep the evidence queries in D8 |
| 3 | Impersonating the writer is an IAM Credentials call, not a BigQuery call, so the BigQuery-only sink doesn't capture it | Widen the sink filter to `iamcredentials.googleapis.com` (data access logs must be on) |
| 4 | Identities named in no policy see zero rows. This makes E11 fingerprints pass falsely and F2's scale build come out empty | Put the writer and any check identity in `rls_all_rows`; `publish.py` step 5 checks this |
| 5 | `map_tenant_access` checks `is_customer` on the child account, not the root | Check it on the root account (section 2.1) |
| 6 | A vendor child under a customer parent inherits the customer's tenant | Decide in B7: stop the hierarchy walk at non-customer accounts, or exclude their stores |
| 7 | `changed_by_user_id` isn't tokenised in the plan | `changed_by_token` |
| 8 | `store_access.principal` is plain email in `sec_{env}`, so the C9 email scan flags it | Allow-list it |
| 9 | CI and local dbt can't read `keys.token_key` or tagged columns | Test key, or a stub macro, for `ci` and `local` |
| 10 | Native views over row-policy tables | Wait for spike 4 (POC C owner) |
| 11 | The policy grantee lists change whenever a tenant principal is added | A Google group for tenant readers, if the team can create one |
| 12 | Several relationships in the POC B schema have no checks (marked TBD there): missing parent, parent cycle, store with an unknown account | Add dbt `relationships` tests. A parent cycle would break the root-account walk, and with it the tenant |
