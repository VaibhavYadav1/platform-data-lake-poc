{{ config(cluster_by=['tenant_id', 'status_color']) }}
-- The headline answer: each active store's colour, why, since when, the alert driving it, what to do, who owns it,
-- and 30-day downtime. Stays a dbt table: the rule logic is beyond a native materialized view.
-- status_reason is the first that holds: RED_CRITICAL, YELLOW_DEGRADED, YELLOW_UNCLASSIFIED, GREEN_INFO_ONLY, GREEN_NO_OPEN_ALERTS.
with snap as (select {{ snapshot_ts() }} as snapshot_ts),
counts as (
  select
    store_id,
    countif(is_open)                                                    as total_alert_count,
    countif(is_open and effective_color = 'RED')                        as red_alert_count,
    countif(is_open and effective_color = 'YELLOW' and not is_unclassified) as yellow_alert_count,
    countif(is_open and is_unclassified)                                as unclassified_alert_count,
    max(alert_time)                                                     as last_alert_start,
    min(if(is_open and effective_color = 'RED', alert_time, null))      as red_since,
    min(if(is_open and effective_color = 'YELLOW', alert_time, null))   as yellow_since,
    max(resolved_time)                                                  as last_resolved_at,
    max(_source_updated_at)                                             as _source_updated_at
  from {{ ref('mv_incident_health') }}
  group by store_id
),
driving as (   -- worst colour first (classified yellow before unclassified), then oldest, then id
  select *
  from {{ ref('mv_incident_health') }}
  where is_open
  qualify row_number() over (
    partition by store_id
    order by case when effective_color = 'RED' then 4
                  when effective_color = 'YELLOW' and not is_unclassified then 3
                  when is_unclassified then 2
                  else 1 end desc,
             alert_time, incident_id
  ) = 1
),
downtime as (
  select
    d.store_id,
    sum(timestamp_diff(least(d.downtime_end, s.snapshot_ts),
                       greatest(d.downtime_start, timestamp_sub(s.snapshot_ts, interval 30 day)), minute)) as total_downtime_minutes_30d,
    count(*)                                                                                                as downtime_interval_count_30d,
    max(timestamp_diff(least(d.downtime_end, s.snapshot_ts),
                       greatest(d.downtime_start, timestamp_sub(s.snapshot_ts, interval 30 day)), minute)) as longest_downtime_minutes_30d
  from {{ ref('mv_downtime_interval') }} as d
  cross join snap as s
  where d.downtime_end > timestamp_sub(s.snapshot_ts, interval 30 day)
  group by d.store_id
),
staged as (
  select
    st.*,
    coalesce(c.total_alert_count, 0)        as total_alert_count,
    coalesce(c.red_alert_count, 0)          as red_alert_count,
    coalesce(c.yellow_alert_count, 0)       as yellow_alert_count,
    coalesce(c.unclassified_alert_count, 0) as unclassified_alert_count,
    c.last_alert_start, c.red_since, c.yellow_since, c.last_resolved_at, c._source_updated_at as c_updated_at,
    case
      when coalesce(c.red_alert_count, 0) > 0          then 'RED_CRITICAL'
      when coalesce(c.yellow_alert_count, 0) > 0       then 'YELLOW_DEGRADED'
      when coalesce(c.unclassified_alert_count, 0) > 0 then 'YELLOW_UNCLASSIFIED'
      when coalesce(c.total_alert_count, 0) > 0        then 'GREEN_INFO_ONLY'
      else 'GREEN_NO_OPEN_ALERTS'
    end                                      as status_reason
  from {{ ref('dim_store') }} as st
  left join counts as c on c.store_id = st.store_id
  where st.is_active
)
select
  s.store_id,
  s.tenant_id,
  s.store_name,
  case when s.status_reason = 'RED_CRITICAL' then 'RED'
       when s.status_reason like 'YELLOW%'   then 'YELLOW'
       else 'GREEN' end                                                         as status_color,
  s.status_reason,
  case s.status_reason
    when 'RED_CRITICAL'        then r.display_label
    when 'YELLOW_DEGRADED'     then r.display_label
    when 'YELLOW_UNCLASSIFIED' then 'Unclassified alert'
    when 'GREEN_INFO_ONLY'     then 'Informational'
    else 'All clear' end                                                        as status_label,
  case s.status_reason
    when 'RED_CRITICAL'        then r.description
    when 'YELLOW_DEGRADED'     then r.description
    when 'YELLOW_UNCLASSIFIED' then 'An open alert has no health rule'
    when 'GREEN_INFO_ONLY'     then 'Only informational alerts are open'
    else 'No open alerts' end                                                   as status_description,
  case s.status_reason
    when 'RED_CRITICAL'        then r.recommended_action
    when 'YELLOW_DEGRADED'     then r.recommended_action
    when 'YELLOW_UNCLASSIFIED' then 'Review the alert and add a health rule'
    else 'No action needed' end                                                 as recommended_action,
  case s.status_reason
    when 'RED_CRITICAL'                              then s.red_since
    when 'YELLOW_DEGRADED'                           then s.yellow_since
    when 'YELLOW_UNCLASSIFIED'                       then s.yellow_since
    else s.last_resolved_at end                                                 as status_since,
  timestamp_diff(sn.snapshot_ts,
    case s.status_reason when 'RED_CRITICAL' then s.red_since
                         when 'YELLOW_DEGRADED' then s.yellow_since
                         when 'YELLOW_UNCLASSIFIED' then s.yellow_since
                         else s.last_resolved_at end, minute)                   as status_duration_minutes,
  s.total_alert_count,
  s.red_alert_count,
  s.yellow_alert_count,
  s.unclassified_alert_count,
  s.last_alert_start,
  if(starts_with(s.status_reason, 'GREEN'), null, dr.incident_id)               as driving_incident_id,
  if(starts_with(s.status_reason, 'GREEN'), null, dr.alert_name)                as driving_alert_name,
  if(starts_with(s.status_reason, 'GREEN'), null, dr.severity)                  as driving_severity,
  if(starts_with(s.status_reason, 'GREEN'), null, dr.customer_category_name)    as driving_customer_category,
  if(starts_with(s.status_reason, 'GREEN'), null, dd.installed_location)        as driving_installed_location_name,
  if(starts_with(s.status_reason, 'GREEN'), null, dd.main_door_indicator)       as driving_main_door_indicator,
  if(starts_with(s.status_reason, 'GREEN'), null, dr.health_rule_id)            as driving_rule_id,
  if(starts_with(s.status_reason, 'GREEN'), null,
     coalesce(stt.next_step_action, aty.not_started_next_step_action))          as next_step_action,
  if(starts_with(s.status_reason, 'GREEN'), null, fa.assignee_token)            as next_step_owner_token,
  if(starts_with(s.status_reason, 'GREEN'), null, fa.assignee_team_name)        as owner_team,
  cast(coalesce(dt.total_downtime_minutes_30d, 0) as int64)                     as total_downtime_minutes_30d,
  round(1 - coalesce(dt.total_downtime_minutes_30d, 0) / 43200, 6)              as uptime_pct_30d,
  cast(coalesce(dt.downtime_interval_count_30d, 0) as int64)                    as downtime_interval_count_30d,
  cast(coalesce(dt.longest_downtime_minutes_30d, 0) as int64)                   as longest_downtime_minutes_30d,
  sn.snapshot_ts,
  {{ hierarchy_columns('s') }},
  {{ lineage_columns('g2', 'coalesce(s.c_updated_at, s._source_updated_at)') }}
from staged as s
cross join snap as sn
left join driving                              as dr  on dr.store_id = s.store_id
left join {{ ref('map_store_health_rule') }}   as r   on r.rule_id = dr.health_rule_id
left join {{ ref('fct_alert') }}               as fa  on fa.incident_id = dr.incident_id
left join {{ ref('status') }}                  as stt on stt.status_id = fa.status_id
left join {{ ref('dim_alert_type') }}          as aty on aty.alert_type_id = dr.alert_type_id
left join {{ ref('dim_device') }}              as dd  on dd.device_id = fa.device_id
left join downtime                             as dt  on dt.store_id = s.store_id
