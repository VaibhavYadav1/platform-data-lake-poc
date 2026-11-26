-- C7: no history event of a quarantined incident reaches the fact (it is in quarantine_alert_history instead).
select f.history_id, f.incident_id
from {{ ref('fct_alert_history') }} as f
join {{ ref('quarantine_alert') }} as q using (incident_id)
