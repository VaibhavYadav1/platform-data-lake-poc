with poc1 as (
  select id as history_id, fk_alert_incident as incident_id, changed_date as event_time, change_type,
         fk_previous_status as previous_status_id, fk_new_status as new_status_id
  from `{baseline_project}.poc1_baseline.fct_alert_history`
),
p2 as (
  select history_id, incident_id, event_time, change_type, previous_status_id, new_status_id
  from `{project}.dbt_{user}_build.fct_alert_history`
  where not is_deleted
)
select 'only_in_poc1' as side, * from (select * from poc1 except distinct select * from p2)
union all
select 'only_in_poc2' as side, * from (select * from p2 except distinct select * from poc1)
