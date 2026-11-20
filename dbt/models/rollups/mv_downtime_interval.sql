{{ config(cluster_by=['tenant_id', 'store_id']) }}
-- Periods when a store had at least one RED alert open. Overlapping alerts merge into one period (gaps and islands).
with red as (
  select
    store_id, incident_id, downtime_cause_type, is_open, snapshot_ts, _source_updated_at,
    alert_time                                  as s,
    coalesce(resolved_time, snapshot_ts)        as e
  from {{ ref('mv_incident_health') }}
  where counts_as_downtime
),
flagged as (
  select *,
    max(e) over (partition by store_id order by s, incident_id
                 rows between unbounded preceding and 1 preceding) as prev_max_e
  from red
),
islands as (
  select *,
    sum(if(prev_max_e is null or s > prev_max_e, 1, 0))
      over (partition by store_id order by s, incident_id) as interval_seq
  from flagged
),
merged as (
  select
    store_id,
    interval_seq,
    min(s)                                         as downtime_start,
    max(e)                                         as downtime_end,
    logical_or(is_open)                            as is_ongoing,
    count(*)                                       as incident_count,
    array_agg(incident_id order by s, incident_id) as contributing_incident_ids,
    array_agg(distinct downtime_cause_type)        as downtime_cause_types,
    max(snapshot_ts)                               as snapshot_ts,
    max(_source_updated_at)                        as _source_updated_at
  from islands
  group by store_id, interval_seq
)
select
  m.store_id,
  cast(m.interval_seq as int64)                                      as interval_seq,
  st.tenant_id,
  st.store_name,
  m.downtime_start,
  m.downtime_end,
  m.is_ongoing,
  timestamp_diff(m.downtime_end, m.downtime_start, minute)           as downtime_minutes,
  m.incident_count,
  m.contributing_incident_ids,
  m.downtime_cause_types,
  m.snapshot_ts,
  {{ hierarchy_columns('st') }},
  {{ lineage_columns('g2', 'm._source_updated_at') }}
from merged as m
left join {{ ref('dim_store') }} as st on st.store_id = m.store_id
