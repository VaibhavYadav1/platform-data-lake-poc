{{ config(severity='warn') }}
-- AT-26b guard: golden_store_health passes trivially when the seed has no rows for this checkpoint.
-- This warns until the scenario owner fills seeds/golden_store_health.csv, so an empty seed is never read as a pass.
select '{{ var('golden_step') }}' as after_step, 'no golden scenarios for this checkpoint' as problem
from (select count(*) as n from {{ ref('golden_store_health') }} where after_step = '{{ var('golden_step') }}')
where n = 0
