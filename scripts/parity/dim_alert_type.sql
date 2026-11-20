with poc1 as (
  select id as alert_type_id, alert_name, alert_description, customer_alert_name, category_name,
         customer_category_name, severity, device_type, system_type, customer_facing, default_priority, is_active
  from `{project}.poc1_baseline.dim_alert_type`
),
p2 as (
  select alert_type_id, alert_name, alert_description, customer_alert_name, category_name,
         customer_category_name, severity, device_type, system_type, customer_facing, default_priority, is_active
  from `{project}.dbt_{user}_build.dim_alert_type`
)
select 'only_in_poc1' as side, * from (select * from poc1 except distinct select * from p2)
union all
select 'only_in_poc2' as side, * from (select * from p2 except distinct select * from poc1)
