-- C7 (error): more than quarantine_error_pct percent of incidents quarantined means a broken feed or a
-- broken rule, not a few bad rows. Publishing stops. Below the limit, the per-check warn tests report the rows.
with counts as (
  select countif(_dq_status = 'QUARANTINE') as quarantined, count(*) as total
  from {{ ref('int_alert__validated') }}
)
select quarantined, total, round(100 * quarantined / total, 2) as quarantined_pct
from counts
where total > 0 and 100 * quarantined / total > {{ var('quarantine_error_pct') }}
