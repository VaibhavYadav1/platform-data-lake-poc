-- Tenant per G2 store (B7): G2 store -> its one Active CRM record -> account -> top-level account.
-- When a step fails the tenant is null and the reason is recorded (flagged, never guessed).
with active as (
  select g2_store_id, crm_store_id, account_id,
         count(*) over (partition by g2_store_id) as n_active
  from {{ ref('int_crm__store') }}
  where status = 'Active'
),
acct as (
  select a.account_id, t.tenant_id, t.hierarchy_depth, ta.customer_type_code, ta.status
  from {{ ref('int_crm__account') }} as a
  left join {{ ref('int_account__tenant') }} as t  on t.account_id = a.account_id
  left join {{ ref('int_crm__account') }}    as ta on ta.account_id = t.tenant_id
)
select
  s.store_id,
  if(r.n_active = 1, r.crm_store_id, null)                     as crm_store_id,
  if(r.n_active = 1, r.account_id, null)                       as account_id,
  case when r.n_active = 1 then a.tenant_id end                as tenant_id,
  case when r.n_active = 1 then a.hierarchy_depth end          as hierarchy_depth,
  coalesce(r.n_active = 1 and {{ is_customer('m.customer_type_enum', 'a.status') }}, false) as is_customer_store,
  case
    when r.g2_store_id is null then 'NO_CRM_RECORD'            -- DQ37
    when r.n_active > 1        then 'MULTIPLE_ACTIVE_RECORDS'  -- DQ46
    when a.account_id is null  then 'UNKNOWN_ACCOUNT'          -- DQ46
    when a.tenant_id is null   then 'BROKEN_HIERARCHY'         -- DQ45
    else 'ASSIGNED'
  end                                                          as tenant_reason,
  s._source_updated_at
from {{ ref('stg_g2__stores') }} as s
left join active as r                         on r.g2_store_id = s.store_id
left join acct   as a                         on a.account_id  = r.account_id
left join {{ ref('map_customer_type') }} as m on m.customer_type_code = a.customer_type_code
where not s.is_deleted
qualify row_number() over (partition by s.store_id order by r.crm_store_id) = 1
