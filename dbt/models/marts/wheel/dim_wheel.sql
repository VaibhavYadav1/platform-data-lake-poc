select
  w.wheel_id,
  st.tenant_id,
  w.g2_store_id        as store_id,
  w.cart_id,
  w.installed_at,
  w.status,
  {{ lineage_columns('g2_datalake', 'w.installed_at') }}
from {{ ref('stg_g2dl__wheel') }} as w
left join {{ ref('dim_store') }}  as st on st.store_id = w.g2_store_id
