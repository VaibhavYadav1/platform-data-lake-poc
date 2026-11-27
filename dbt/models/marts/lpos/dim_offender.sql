{{ config(enabled=false) }}
{# Disabled: depends on stg_lpos__case_event which is not available #}
-- Repeat offenders per tenant. Per tenant on purpose: one tenant cannot learn that a token exists at another.
select
  {{ dbt_utils.generate_surrogate_key(['st.tenant_id', 'e.offender_token']) }} as offender_key,
  st.tenant_id,
  e.offender_token,
  min(e.event_ts)                  as first_seen_at,
  max(e.event_ts)                  as last_seen_at,
  count(distinct e.case_id)        as case_count,
  'lpos'                           as _source_system,
  max(e.publish_time)              as _source_updated_at,
  current_timestamp()              as _dbt_loaded_at,
  '{{ invocation_id }}'            as _dbt_invocation_id
from {{ ref('stg_lpos__case_event') }} as e
left join {{ ref('dim_store') }}       as st on st.store_id = e.g2_store_id
where e.offender_token is not null
group by st.tenant_id, e.offender_token
