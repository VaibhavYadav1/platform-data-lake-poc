{{ config(severity='warn') }}
-- DQ28 (warning, from POC 1): the latest status event of an incident does not end in the incident's status.
-- Latest = newest event_time among events with a new status (ties: highest history_id).
with latest as (
  select incident_id, new_status_id
  from {{ ref('fct_alert_history') }}
  where new_status_id is not null and not is_deleted
  qualify row_number() over (partition by incident_id order by event_time desc, history_id desc) = 1
)
select a.incident_id, a.status_id, l.new_status_id
from {{ ref('fct_alert') }} as a
join latest as l using (incident_id)
where not a.is_deleted and a.status_id is not null and l.new_status_id != a.status_id
