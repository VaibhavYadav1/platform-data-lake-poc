with poc1 as (
  select id as device_id, fk_store as store_id, installed_location, type as device_type, main_door_indicator, location_class
  from `{project}.poc1_baseline.dim_device`
),
p2 as (
  select device_id, store_id, installed_location, device_type, main_door_indicator, location_class
  from `{project}.dbt_{user}_build.dim_device`
)
select 'only_in_poc1' as side, * from (select * from poc1 except distinct select * from p2)
union all
select 'only_in_poc2' as side, * from (select * from p2 except distinct select * from poc1)
