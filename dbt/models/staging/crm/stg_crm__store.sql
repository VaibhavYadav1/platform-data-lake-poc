select
  crm_store_id,
  trim(account_id)                    as account_id,
  upper(trim(g2_store_id))            as g2_store_id,
  initcap(trim(status))               as status,
  updated_at,
  export_ts
from {{ source('raw_crm', 'store_landing') }}
