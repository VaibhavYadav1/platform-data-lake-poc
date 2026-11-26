select
  work_order_id,
  trim(account_id)                    as account_id,
  trim(crm_store_id)                  as crm_store_id,
  nullif(trim(g2_device_id), '')      as g2_device_id,
  upper(trim(work_type))              as work_type,
  upper(trim(status))                 as status,
  opened_at,
  closed_at,
  updated_at,
  export_ts
from {{ source('raw_crm', 'work_order_landing') }}
