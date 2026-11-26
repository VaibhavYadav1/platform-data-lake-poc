{{ config(cluster_by=['tenant_id', 'store_id']) }}
-- The work queue: one row per (store, door) with at least one open health-relevant incident; active stores only.
with open_i as (
  select
    i.*,
    d.installed_location,
    d.main_door_indicator,
    aty.system_type,
    aty.alert_description,
    fa.assignee_token,
    fa.assignee_team_name,
    coalesce(stt.next_step_action, aty.not_started_next_step_action)           as next_step_action,
    concat(i.store_id, '|', coalesce(d.installed_location, '__UNKNOWN__'))     as issue_id
  from {{ ref('mv_incident_health') }} as i
  join {{ ref('fct_alert') }}          as fa  on fa.incident_id = i.incident_id
  left join {{ ref('dim_device') }}    as d   on d.device_id = fa.device_id
  left join {{ ref('dim_alert_type') }} as aty on aty.alert_type_id = i.alert_type_id
  left join {{ ref('status') }}        as stt on stt.status_id = fa.status_id
  where i.is_open
),
primary_i as (   -- worst effective colour, then oldest alert_time, then id
  select *
  from open_i
  qualify row_number() over (
    partition by issue_id
    order by case effective_color when 'RED' then 3 when 'YELLOW' then 2 else 1 end desc, alert_time, incident_id
  ) = 1
),
agg as (
  select
    issue_id,
    array_agg(incident_id order by alert_time, incident_id) as alert_ids,
    min(alert_time)                                         as issue_opened_at
  from open_i
  group by issue_id
)
select
  p.issue_id,
  st.tenant_id,
  g.alert_ids,
  p.incident_id                    as primary_alert_id,
  p.store_id,
  st.store_name,
  st.store_number,
  p.system_type,
  p.main_door_indicator,
  p.installed_location             as installed_location_name,
  p.alert_name,
  p.alert_description,
  p.customer_category_name         as issue_type,
  p.severity,
  p.effective_color                as issue_color,
  p.is_unclassified,
  p.assignee_token                 as issue_owner_token,
  p.assignee_team_name             as owner_team,
  p.next_step_action,
  g.issue_opened_at,
  p.snapshot_ts,
  {{ hierarchy_columns('st') }},
  {{ lineage_columns('g2', 'p._source_updated_at') }}
from primary_i as p
join agg as g on g.issue_id = p.issue_id
join {{ ref('dim_store') }} as st on st.store_id = p.store_id and st.is_active
