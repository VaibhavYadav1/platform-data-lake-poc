{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key='history_id',
    partition_by={'field': 'event_date', 'data_type': 'date'},
    cluster_by=['tenant_id', 'store_id', 'device_id']
) }}
-- Incremental merge on history_id, like fct_alert (A11). Comment text is kept; the daily scan checks it for emails (DQ41).
with final as (
  select
    h.history_id,
    a.tenant_id,
    h.incident_id,
    h.event_timestamp                                   as event_time,
    date(h.event_timestamp)                             as event_date,
    h.event_type                                        as change_type,
    case h.event_type
      when 'CREATED'            then 'New alert created'
      when 'ASSIGNED'           then 'Alert assigned'
      when 'STATUS_CHANGED'     then 'Status changed'
      when 'COMMENT'            then 'Comment added'
      when 'RESOLVED'           then 'Alert resolved'
      when 'REOPENED'           then 'Alert reopened'
      when 'MONITORING_TIMEOUT' then 'Monitoring timed out'
      else h.event_type
    end                                                 as change,
    ps.status_id                                        as previous_status_id,
    ns.status_id                                        as new_status_id,
    {{ tokenize('h.changed_by_user_id') }}              as changed_by_token,
    h.comments,
    a.store_id,
    a.device_id,
    a.alert_type_id,
    {{ hierarchy_columns('a') }},
    h.is_deleted,
    h.deleted_at,
    {{ lineage_columns('g2', 'h._source_updated_at') }}
  from {{ ref('stg_g2__alert_history') }} as h
  left join {{ ref('fct_alert') }} as a  on a.incident_id = h.incident_id   -- orphan events keep null store/device
  left join {{ ref('status') }}    as ps on ps.status_name = h.previous_status
  left join {{ ref('status') }}    as ns on ns.status_name = h.new_status
)
select * from final as src
{{ incremental_filter('history_id') }}
