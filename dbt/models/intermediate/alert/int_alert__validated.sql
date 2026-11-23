-- Alert checks run once (C7). Every incident is kept here and tagged; nothing is dropped.
-- Critical => QUARANTINE (kept out of fct_alert, listed in quarantine_alert):
--   DQ33                unknown or deleted device or store
--   UNKNOWN_ALERT_TYPE  unknown or deleted alert type (POC 1 UNKNOWN_REFERENCE)
--   DQ34                created_at or resolved_at more than future_tolerance_minutes after the run's as-of time
--   DQ38                resolved before it opened
-- Warning => WARN (loaded and flagged; POC 1 consistency rules, now report-only):
--   UNKNOWN_STATUS        current_status not in the status list (POC 1 BAD_ENUM)
--   DQ08                  device is installed at another store (devices may move, so not critical)
--   DEVICE_TYPE_MISMATCH  device type differs from the alert type's device type
--   DQ13                  resolved_at filled but status not closed, or the other way round
--   DQ25                  open incident at an inactive store
--   DQ29                  overlaps an earlier incident of the same alert_id (the later one is flagged)
--   BAD_ALERT_ID          alert_id is not ALR-<device_id>-<alert_type_id>
-- Type and format rules (BAD_TYPE, BAD_PATTERN) are enforced at source by PostgreSQL.
-- "Now" is snapshot_ts(): one as-of time for the whole run, so a re-run gives the same answer.
{% set future_limit = "timestamp_add(" ~ snapshot_ts() ~ ", interval " ~ var('future_tolerance_minutes') ~ " minute)" %}
with flagged as (
  select
    i.*,
    array(select r from unnest([
      if(dl.device_id is null or st.store_id is null, 'DQ33', null),
      if(aty.alert_type_id is null, 'UNKNOWN_ALERT_TYPE', null),
      if(i.created_at > {{ future_limit }} or i.resolved_at > {{ future_limit }}, 'DQ34', null),
      if(i.resolved_at < i.created_at, 'DQ38', null)
    ]) as r where r is not null)                                               as critical_reasons,
    array(select r from unnest([
      if(sx.status_id is null, 'UNKNOWN_STATUS', null),
      if(dl.store_id != i.store_id, 'DQ08', null),
      if(dl.device_type != aty.device_type, 'DEVICE_TYPE_MISMATCH', null),
      if(sx.status_id is not null and (i.resolved_at is not null) != coalesce(sx.is_closed, false), 'DQ13', null),
      if({{ is_open_alert('i.resolved_at', 'i.is_deleted') }} and st.is_active = false, 'DQ25', null),
      if(i.alert_id != concat('ALR-', i.device_id, '-', i.alert_type_id), 'BAD_ALERT_ID', null)
    ]) as r where r is not null)                                               as warning_reasons
  from {{ ref('stg_g2__alert_incidents') }} as i
  left join {{ ref('stg_g2__device_locations') }} as dl  on dl.device_id = i.device_id and not dl.is_deleted
  left join {{ ref('stg_g2__stores') }}           as st  on st.store_id  = i.store_id  and not st.is_deleted
  left join {{ ref('stg_g2__alert_types') }}      as aty on aty.alert_type_id = i.alert_type_id and not aty.is_deleted
  left join {{ ref('stg_g2__statuses') }}         as sx  on sx.status_name = i.current_status and not sx.is_deleted
),
-- DQ29 needs the other incidents of the same alert_id. Only incidents that will be loaded are compared
-- (not quarantined, not deleted). An incident with no resolved_at is open indefinitely; back-to-back is not an overlap.
overlap as (
  select
    incident_id,
    max(coalesce(resolved_at, timestamp '9999-12-31')) over (
      partition by alert_id order by created_at, incident_id
      rows between unbounded preceding and 1 preceding
    ) > created_at                                                             as overlaps_earlier
  from flagged
  where array_length(critical_reasons) = 0 and not is_deleted
),
reasons as (
  select
    f.* except (warning_reasons),
    array_concat(f.warning_reasons,
                 if(coalesce(o.overlaps_earlier, false), ['DQ29'], cast([] as array<string>))) as warning_reasons
  from flagged as f
  left join overlap as o on o.incident_id = f.incident_id
)
select
  * except (critical_reasons, warning_reasons),
  case
    when array_length(critical_reasons) > 0 then 'QUARANTINE'
    when array_length(warning_reasons)  > 0 then 'WARN'
    else 'PASS'
  end                                             as _dq_status,
  array_concat(critical_reasons, warning_reasons) as _dq_reasons
from reasons
