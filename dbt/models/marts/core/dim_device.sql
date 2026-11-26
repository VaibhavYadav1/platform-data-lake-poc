select
  d.device_id,
  st.tenant_id,
  d.store_id,
  d.installed_location,
  d.device_type,
  d.main_door_indicator,
  if(d.main_door_indicator, 'MAIN_DOOR', 'OTHER')  as location_class,
  {{ hierarchy_columns('st', with_country=false) }},
  {{ lineage_columns('g2', 'd._source_updated_at') }}
from {{ ref('stg_g2__device_locations') }} as d
left join {{ ref('dim_store') }} as st on st.store_id = d.store_id
where not d.is_deleted
