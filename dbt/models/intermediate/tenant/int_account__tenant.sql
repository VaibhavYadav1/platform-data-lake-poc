-- Top-level account (the tenant) for every account whose parent chain reaches a root (D-23).
-- Accounts with a loop, a missing parent or a chain deeper than 10 do not appear here (DQ45).
with recursive chain as (
  select account_id as start_id, account_id, parent_account_id, 0 as depth
  from {{ ref('int_crm__account') }}
  union all
  select c.start_id, a.account_id, a.parent_account_id, c.depth + 1
  from chain as c
  join {{ ref('int_crm__account') }} as a on a.account_id = c.parent_account_id
  where c.depth < 10
)
select start_id as account_id, account_id as tenant_id, depth as hierarchy_depth
from chain
where parent_account_id is null
