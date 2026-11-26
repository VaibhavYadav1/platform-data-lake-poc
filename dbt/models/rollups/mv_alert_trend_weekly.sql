{{ config(
    partition_by={'field': 'week_start', 'data_type': 'date'},
    cluster_by=['tenant_id', 'store_id']
) }}
-- Weekly rollup computed from fct_alert (distinct alert_id cannot be summed from days), with the change from the previous week.
with weekly as (
  select
    date_trunc(alert_date, isoweek)  as week_start,
    store_id,
    alert_type_id,
    count(*)                         as incident_count,
    count(distinct alert_id)         as distinct_alert_count
  from {{ ref('fct_alert') }}
  where not is_deleted
  group by week_start, store_id, alert_type_id
)
select
  w.week_start,
  w.store_id,
  w.alert_type_id,
  st.tenant_id,
  aty.customer_alert_name                                                         as alert_name,
  w.incident_count,
  w.distinct_alert_count,
  lag(w.incident_count) over (partition by w.store_id, w.alert_type_id order by w.week_start)  as prev_week_incident_count,
  w.incident_count - lag(w.incident_count) over (partition by w.store_id, w.alert_type_id order by w.week_start) as week_over_week_change,
  {{ snapshot_ts() }}                                                             as snapshot_ts,
  {{ hierarchy_columns('st') }},
  {{ lineage_columns('g2', snapshot_ts()) }}
from weekly as w
left join {{ ref('dim_store') }}      as st  on st.store_id = w.store_id
left join {{ ref('dim_alert_type') }} as aty on aty.alert_type_id = w.alert_type_id
