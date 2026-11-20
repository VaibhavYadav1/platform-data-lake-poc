{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key='incident_id',
    partition_by={'field': 'alert_date', 'data_type': 'date'},
    cluster_by=['tenant_id', 'store_id', 'device_id']
) }}
-- Incremental merge on incident_id (A11): 30-minute lookback and a guard against older changes.
-- A full rebuild (--full-refresh, daily load) fixes anything the incremental filter cannot see, e.g. a store
-- moving to another tenant (DQ39).
with hist as (
  select
    incident_id,
    min(if(event_type = 'ASSIGNED', event_timestamp, null)) as assigned_time,
    max(_source_updated_at)                                 as hist_updated_at
  from {{ ref('stg_g2__alert_history') }}
  where not is_deleted
  group by incident_id
),
final as (
  select
    i.incident_id,
    st.tenant_id,
    i.alert_id,
    i.store_id,
    i.device_id,
    i.alert_type_id,
    aty.customer_alert_name                                   as alert_name,
    sx.status_id,
    i.current_status                                         as status_name,
    i.priority                                               as priority_name,
    {{ tokenize('i.assigned_user_id') }}                     as assignee_token,
    tm.team_name                                             as assignee_team_name,
    h.assigned_time,
    i.created_at                                             as alert_time,
    i.resolved_at                                            as resolved_time,
    date(i.created_at)                                       as alert_date,
    st.brand_id,
    i.brand_id                                               as source_brand_id,
    {{ hierarchy_columns('st') }},
    {{ is_open_alert('i.resolved_at', 'i.is_deleted') }}     as is_open,
    i.is_deleted,
    i.deleted_at,
    i._dq_status,
    i._dq_reasons,
    {{ lineage_columns('g2', 'greatest(i._source_updated_at, coalesce(h.hist_updated_at, i._source_updated_at))') }}
  from {{ ref('int_alert__validated') }} as i
  left join hist                                  as h  on h.incident_id = i.incident_id
  left join {{ ref('dim_store') }}                as st on st.store_id = i.store_id
  left join {{ ref('dim_alert_type') }}           as aty on aty.alert_type_id = i.alert_type_id
  left join {{ ref('status') }}                   as sx on sx.status_name = i.current_status
  left join {{ ref('stg_g2__users') }}            as u  on u.user_id = i.assigned_user_id
  left join {{ ref('stg_g2__teams') }}            as tm on tm.team_id = u.team_id
  where i._dq_status != 'QUARANTINE'
)
select * from final as src
{{ incremental_filter('incident_id') }}
