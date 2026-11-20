with poc1 as (
  select id as incident_id, alert_id, fk_store as store_id, fk_device as device_id, alert_type as alert_type_id,
         fk_status as status_id, priority_name, alert_time, resolved_time
  from `{project}.poc1_baseline.fct_alert_incident`
),
p2 as (
  select incident_id, alert_id, store_id, device_id, alert_type_id, status_id, priority_name, alert_time, resolved_time
  from `{project}.dbt_{user}_build.fct_alert`
  where not is_deleted
)
select 'only_in_poc1' as side, * from (select * from poc1 except distinct select * from p2)
union all
select 'only_in_poc2' as side, * from (select * from p2 except distinct select * from poc1)
