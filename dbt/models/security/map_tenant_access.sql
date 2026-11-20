-- Who may see which tenant. Row access policies filter on it with SESSION_USER() (D3, D4).
-- principal is a plain email by decision 3. A grant on a child account gives its top-level tenant,
-- and only customer accounts may be tenants (AT-19 check 2).
select distinct
  a.principal,
  t.tenant_id
from {{ ref('stg_g2__store_access') }} as a
join {{ ref('dim_account') }}          as acc on acc.account_id = a.crm_account_id
join {{ ref('dim_account') }}          as t   on t.account_id = acc.tenant_id and t.is_customer
where not a.is_deleted
