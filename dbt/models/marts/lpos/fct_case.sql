{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key='case_id',
    partition_by={'field': 'case_date', 'data_type': 'date'},
    cluster_by=['tenant_id', 'store_id', 'case_id']
) }}
-- One row per case: its latest event. Incremental on case_id: any case with a new event is rebuilt from ALL its events.
-- A case at an unknown store is kept with tenant_id null and flagged DQ44.
with changed as (
  select distinct case_id
  from {{ ref('stg_lpos__case_event') }}
  {% if is_incremental() %}
  where publish_time >= timestamp_sub(
          (select coalesce(max(_source_updated_at), timestamp '1970-01-01') from {{ this }}),
          interval {{ var('incremental_lookback_minutes') }} minute)
  {% endif %}
),
ev as (
  select e.*
  from {{ ref('stg_lpos__case_event') }} as e
  join changed using (case_id)
),
agg as (
  select
    case_id,
    array_agg(struct(event_id, event_type, event_ts, g2_store_id, case_status)
              order by event_ts desc, event_id desc limit 1)[offset(0)]               as lst,
    array_agg(offender_token ignore nulls order by event_ts desc limit 1)[safe_offset(0)] as offender_token,
    array_agg(loss_amount    ignore nulls order by event_ts desc limit 1)[safe_offset(0)] as loss_amount,
    array_agg(items_count    ignore nulls order by event_ts desc limit 1)[safe_offset(0)] as items_count,
    min(event_ts)                                         as first_event_at,
    min(if(event_type = 'CASE_OPENED', event_ts, null))   as opened_ts,
    max(if(event_type = 'CASE_CLOSED', event_ts, null))   as closed_at,
    max(event_ts)                                         as last_event_at,
    count(distinct event_id)                              as event_count,
    max(publish_time)                                     as last_publish_time
  from ev
  group by case_id
)
select
  a.case_id,
  st.tenant_id,
  a.lst.g2_store_id                                       as store_id,
  a.offender_token,
  a.lst.case_status                                       as case_status,
  a.lst.event_type                                        as last_event_type,
  a.lst.event_id                                          as last_event_id,
  coalesce(a.opened_ts, a.first_event_at)                 as opened_at,
  a.closed_at,
  a.last_event_at,
  date(coalesce(a.opened_ts, a.first_event_at))           as case_date,
  a.loss_amount,
  a.items_count,
  a.event_count,
  a.lst.case_status != 'CLOSED'                           as is_open,
  if(st.store_id is null, 'WARN', 'PASS')                 as _dq_status,
  if(st.store_id is null, ['DQ44'], cast([] as array<string>)) as _dq_reasons,
  {{ lineage_columns('lpos', 'a.last_publish_time') }}
from agg as a
left join {{ ref('dim_store') }} as st on st.store_id = a.lst.g2_store_id
