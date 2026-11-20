{{ config(
    partition_by={'field': 'alert_date', 'data_type': 'date'},
    cluster_by=['tenant_id', 'store_id']
) }}
-- The dbt version (kept in build for parity) fills every day with zeros. The native view in wh has no zero days
-- (orchestration/publish/objects/mv_alert_trend_daily.sql). AT-34 compares them on days with alerts.
with days as (
  select date_day
  from {{ ref('dim_date') }}
  where date_day between (select min(alert_date) from {{ ref('fct_alert') }}) and current_date()
),
counts as (
  select store_id, alert_type_id, alert_date,
         count(*)                  as incident_count,
         count(distinct alert_id)  as distinct_alert_count
  from {{ ref('fct_alert') }}
  where not is_deleted
  group by store_id, alert_type_id, alert_date
)
select
  d.date_day                                                   as alert_date,
  st.store_id,
  aty.alert_type_id,
  st.tenant_id,
  aty.customer_alert_name                                      as alert_name,
  coalesce(c.incident_count, 0)                                as incident_count,
  coalesce(c.distinct_alert_count, 0)                          as distinct_alert_count,
  coalesce(c.incident_count, 0) - coalesce(c.distinct_alert_count, 0) as repeat_incident_count,
  {{ snapshot_ts() }}                                          as snapshot_ts,
  {{ hierarchy_columns('st') }},
  {{ lineage_columns('g2', snapshot_ts()) }}
from {{ ref('dim_store') }} as st
cross join {{ ref('dim_alert_type') }} as aty
cross join days as d
left join counts as c
  on c.store_id = st.store_id and c.alert_type_id = aty.alert_type_id and c.alert_date = d.date_day
where st.is_active
