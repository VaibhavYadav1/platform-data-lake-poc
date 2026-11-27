{{ config(enabled=false) }}
{# Disabled: seed table not loading properly yet #}
-- AT-26b: mv_store_health must match the golden scenarios for the checkpoint in var golden_step.
-- Run after the scripted batch that creates each state. Passes trivially while the seed is empty.
select g.scenario_id, g.store_id, g.expected_status_color, h.status_color, g.expected_status_reason, h.status_reason
from {{ ref('golden_store_health') }} as g
left join {{ ref('mv_store_health') }} as h on h.store_id = g.store_id
where g.after_step = '{{ var('golden_step') }}'
  and (h.store_id is null
       or h.status_color  != g.expected_status_color
       or h.status_reason != g.expected_status_reason
       or coalesce(h.driving_rule_id, '') != coalesce(nullif(g.expected_driving_rule_id, ''), ''))
