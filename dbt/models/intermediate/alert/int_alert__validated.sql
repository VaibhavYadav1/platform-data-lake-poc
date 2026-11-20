-- Alert checks run once (C7). Critical (DQ33, DQ34, DQ38) => QUARANTINE. Warnings => WARN.
-- Type and format rules (BAD_TYPE, BAD_PATTERN) are enforced at source by PostgreSQL.
with flagged as (
  select
    i.*,
    array(select r from unnest([
      if(dl.device_id is null or st.store_id is null, 'DQ33', null),
      if(i.created_at > timestamp_add(current_timestamp(), interval {{ var('future_tolerance_minutes') }} minute), 'DQ34', null),
      if(i.resolved_at < i.created_at, 'DQ38', null)
    ]) as r where r is not null)                                               as critical_reasons,
    array(select r from unnest([
      if(sx.status_id is null, 'UNKNOWN_STATUS', null)
    ]) as r where r is not null)                                               as warning_reasons
  from {{ ref('stg_g2__alert_incidents') }} as i
  left join {{ ref('stg_g2__device_locations') }} as dl on dl.device_id = i.device_id and not dl.is_deleted
  left join {{ ref('stg_g2__stores') }}           as st on st.store_id  = i.store_id  and not st.is_deleted
  left join {{ ref('stg_g2__statuses') }}         as sx on sx.status_name = i.current_status and not sx.is_deleted
)
select
  * except (critical_reasons, warning_reasons),
  case
    when array_length(critical_reasons) > 0 then 'QUARANTINE'
    when array_length(warning_reasons)  > 0 then 'WARN'
    else 'PASS'
  end                                         as _dq_status,
  array_concat(critical_reasons, warning_reasons) as _dq_reasons
from flagged
