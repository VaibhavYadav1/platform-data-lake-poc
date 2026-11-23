{{ config(severity='warn') }}
-- DQ27 (warning, from POC 1): a history event dated before its incident's alert time.
select h.history_id, h.incident_id, h.event_time, a.alert_time
from {{ ref('fct_alert_history') }} as h
join {{ ref('fct_alert') }} as a using (incident_id)
where not h.is_deleted and h.event_time < a.alert_time
