{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key='event_id',
    partition_by={'field': 'event_date', 'data_type': 'date'},
    cluster_by=['tenant_id', 'store_id', 'wheel_id']
) }}
-- Incremental on the lake's _loaded_at with a lookback, so a late event is not missed.
-- An event for an unknown wheel is kept with store and tenant null, and flagged DQ43.
with final as (
  select
    e.event_id,
    w.tenant_id,
    w.store_id,
    e.wheel_id,
    e.event_type,
    e.event_ts,
    date(e.event_ts)                                         as event_date,
    if(w.wheel_id is null, 'WARN', 'PASS')                   as _dq_status,
    if(w.wheel_id is null, ['DQ43'], cast([] as array<string>)) as _dq_reasons,
    {{ lineage_columns('g2_datalake', 'e._loaded_at') }}
  from {{ ref('stg_g2dl__wheel_event') }} as e
  left join {{ ref('dim_wheel') }}        as w on w.wheel_id = e.wheel_id
)
select * from final as src
{{ incremental_filter('event_id') }}
