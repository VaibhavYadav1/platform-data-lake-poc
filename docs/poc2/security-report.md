# Security Report

**Owner:** Dev 2  
**Tasks:** D5-D8

POC D evidence: tenant isolation (AT-24), access removal (AT-25), read-only access with audit evidence (AT-27) and
no personal data in the warehouse (AT-28). Design: `poc-d-security-design.md`. Identities and grants:
`access-matrix.md`. Personal data: `pii-inventory.md`.

**Status: not run yet.** Each section below is filled in from a real run; the tools are in place.

| Step | Tool | Needs first |
|---|---|---|
| D1 spikes | `scripts/spikes/poc_d/` → `spikes.md` | nothing |
| D2 identities, IAM, audit sink | `terraform/shared/security.tf`, `terraform/env/security.tf` | `bq_env` datasets (Dev 4) |
| D3 test grants | `python -m simulator store-access-seed` | G2 seeded (A3) |
| D4 policies | `orchestration/publish/policies/` (applied by `publish.py`) | D2, D3, a dbt build with `map_tenant_access` |
| D5 suite | `scripts/security/test_access.py` | D4 |
| D6 access removal | `scripts/security/access_removal.py` | D5, micro-batch (E4) |
| D7 test app | `apps/tenant_reader` | D2, D4 |
| D8 evidence | `scripts/security/evidence.sql` | D5 run with the sink in place |
| D9 tags | `terraform/modules/policy_tags`, `scripts/security/tag_raw_columns.py` | spike 3, `raw_crm` (B3), `raw_g2` (A4) |
| D10 Looker Studio | checklist below | the report (F5) |

## 1. Access matrix (as applied)

_Paste `access-matrix.md` section 1 after D2 is applied, with any change the spikes caused._

## 2. Tenant isolation (AT-24)

### 2.1 Command line (D5 cases 1 and 6)

| Identity | Table | Own rows | Internal count | Other tenants' rows | Pass |
|---|---|---|---|---|---|

### 2.2 Test application (D7)

| Run | Expected | Result |
|---|---|---|
| `--tenant A --query store_health` | tenant A stores only | |
| `--tenant B --query store_health` | tenant B stores only | |
| `--tenant A --filter-tenant <B's id>` | 0 rows | |
| `--impersonate-writer` | refused | |

### 2.3 Looker Studio (D10)

1. Add the two Looker users to `tenant_principals` in `config.dev.yaml` and to `store_access`
   (`simulator grant`), publish once.
2. Set the report's data credentials to **Viewer**.
3. Open the report as user A, user B and the internal analyst. Take a screenshot of each.
4. Pass: A and B see different stores, none of the other's; the analyst sees all.
5. Remove both users again (`simulator revoke`, config, publish).

| Viewer | Stores seen | Screenshot | Pass |
|---|---|---|---|

## 3. Access removal (AT-25, D6)

| Step | Time | Tenant A rows |
|---|---|---|
| before revoke | | |
| revoke | | |
| rows reach 0 | | |
| grant | | |
| rows back | | |

Pass: 0 rows within 20 minutes; rows back after `grant`.

## 4. Read-only access (AT-27, D5 cases 2–4, D8)

Each blocked attempt, linked to its audit log entry and its `JOBS_BY_PROJECT` row (`evidence.sql`).

| Identity | Attempt | Denied | Job id | Audit log entry |
|---|---|---|---|---|

## 5. Personal data (AT-28)

| Check | Result |
|---|---|
| DQ41 column deny list on every build | |
| DQ41 email-value scan (daily full load) | |
| D5 case 5: `sa-pii-probe` reads `raw_crm.account_landing.primary_contact_email` | masked or denied |
| D9 tags present on the columns in `pii-inventory.md` section 4 | |

## 6. Open decisions

From `poc-d-security-design.md` section 8 and `pii-inventory.md` section 5. Record each answer here.
