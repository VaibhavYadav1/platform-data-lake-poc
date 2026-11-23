{{ config(schema='dq', materialized='table') }}
-- History events of quarantined incidents. Kept out of fct_alert_history together with their incident
-- (as in POC 1, where a rejected incident's history was rejected too), and kept here so nothing is dropped silently.
select h.*, v._dq_reasons as incident_dq_reasons
from {{ ref('stg_g2__alert_history') }} as h
join {{ ref('int_alert__validated') }} as v on v.incident_id = h.incident_id
where v._dq_status = 'QUARANTINE'
