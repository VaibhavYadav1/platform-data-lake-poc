-- Who may see which tenant. Row access policies filter on it with SESSION_USER() (D3, D4).
-- A grant on a child account gives its top-level tenant, and only customer accounts may be tenants (AT-19 check 2).
--
-- Spike 1 (docs/poc2/spikes.md): a reader must be able to read this table itself, and BigQuery allows neither a
-- row policy on it (a table read by row policies may not have its own) nor a view in its place. So every tenant
-- reader can read the whole table. It therefore holds a SHA-256 hash of the email, never the email: readers see
-- hashes and tenant ids, not who belongs to which tenant. The tenant policy hashes SESSION_USER() the same way.
-- Lower-case and trimmed first, as SESSION_USER() returns the lower-case email.
select distinct
  to_hex(sha256(lower(trim(a.principal)))) as principal_hash,
  t.tenant_id
from {{ ref('stg_g2__store_access') }} as a
join {{ ref('dim_account') }}          as acc on acc.account_id = a.crm_account_id
join {{ ref('dim_account') }}          as t   on t.account_id = acc.tenant_id and t.is_customer
where not a.is_deleted
