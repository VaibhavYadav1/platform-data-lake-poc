{{ config(
    partition_by={'field': 'event_date', 'data_type': 'date'},
    cluster_by=['tenant_id', 'store_id']
) }}
-- The dbt version kept in build for comparison with the native materialized view (AT-34).
-- The native view uses APPROX_COUNT_DISTINCT for active_wheels; this one uses COUNT(DISTINCT). Compare with a tolerance.
select
  tenant_id,
  store_id,
  event_date,
  count(*)                              as event_count,
  countif(event_type = 'EXIT_ATTEMPT')  as exit_attempts,
  count(distinct wheel_id)              as active_wheels
from {{ ref('fct_wheel_event') }}
group by tenant_id, store_id, event_date
