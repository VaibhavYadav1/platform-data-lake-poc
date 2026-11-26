{{ config(
    partition_by={'field': 'opened_date', 'data_type': 'date'},
    cluster_by=['tenant_id', 'store_id', 'device_id']
) }}
-- Rebuilt every micro-batch (the table is small). tenant_id comes from the store, like every other fact.
-- DQ47 (warning): unknown account, store or device, or an account that differs from its store's. The row is kept.
with joined as (
  select
    wo.*,
    cs.g2_store_id,
    cs.account_id as store_account_id,
    acc.account_id as known_account_id,
    ds.store_id    as known_store_id,
    ds.tenant_id   as store_tenant_id,
    dd.device_id   as known_device_id
  from {{ ref('int_crm__work_order') }} as wo
  left join {{ ref('int_crm__store') }}  as cs  on cs.crm_store_id = wo.crm_store_id
  left join {{ ref('dim_account') }}     as acc on acc.account_id = wo.account_id
  left join {{ ref('dim_store') }}       as ds  on ds.store_id = cs.g2_store_id
  left join {{ ref('dim_device') }}      as dd  on dd.device_id = wo.g2_device_id
)
select
  work_order_id,
  store_tenant_id                                   as tenant_id,
  account_id,
  crm_store_id,
  known_store_id                                    as store_id,
  known_device_id                                   as device_id,
  work_type,
  status,
  opened_at,
  closed_at,
  date(opened_at)                                   as opened_date,
  status in ('OPEN', 'IN_PROGRESS')                 as is_open,
  if(array_length(dq) > 0, 'WARN', 'PASS')          as _dq_status,
  dq                                                as _dq_reasons,
  {{ lineage_columns('crm', 'updated_at') }}
from (
  select
    *,
    array(select r from unnest([
      if(known_account_id is null
         or known_store_id is null
         or (g2_device_id is not null and known_device_id is null)
         or (store_account_id is not null and store_account_id != account_id), 'DQ47', null)
    ]) as r where r is not null) as dq
  from joined
)
