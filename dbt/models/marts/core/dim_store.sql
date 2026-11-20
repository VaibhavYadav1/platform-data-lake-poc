select
  s.store_id,
  t.tenant_id,
  coalesce(t.is_customer_store, false)                              as is_customer_store,
  trim(concat(coalesce(b.brand_name, ''), ' ', regexp_extract(s.store_id, r'(\d+)'))) as store_name,
  regexp_extract(s.store_id, r'(\d+)')                              as store_number,
  s.brand_id,
  b.brand_name                                                      as brand,
  b.is_active                                                       as brand_is_active,
  b.ultimate_parent,
  s.country,
  s.state,
  s.location_name                                                   as city,
  s.region,
  s.department,
  s.district,
  s.region                                                          as level_1,
  s.department                                                      as level_2,
  s.district                                                        as level_3,
  cast(null as string)                                              as level_4,
  cast(null as string)                                              as level_5,
  cast(null as string)                                              as level_6,
  cast(null as string)                                              as level_7,
  s.is_active,
  (s.country is not null and b.ultimate_parent is not null and s.region is not null
     and s.department is not null and s.district is not null)       as hierarchy_complete,
  {{ lineage_columns('g2', 's._source_updated_at') }}
from {{ ref('stg_g2__stores') }} as s
left join {{ ref('stg_g2__brands') }}    as b on b.brand_id = s.brand_id and not b.is_deleted
left join {{ ref('int_store__tenant') }} as t on t.store_id = s.store_id
where not s.is_deleted
