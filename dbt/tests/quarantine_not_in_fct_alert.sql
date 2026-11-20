-- C7: no quarantined incident reaches the fact.
select f.incident_id
from {{ ref('fct_alert') }} as f
join {{ ref('quarantine_alert') }} as q using (incident_id)
