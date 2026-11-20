-- AT-19 check 2: every tenant in map_tenant_access is a customer account.
select m.principal, m.tenant_id
from {{ ref('map_tenant_access') }} as m
left join {{ ref('dim_account') }} as a on a.account_id = m.tenant_id
where a.account_id is null or not a.is_customer
