{{ config(severity='warn') }}
-- DQ35 (warning): case events delivered more than once. Deduplicated in staging; this reports the count.
select event_id, copies_received from {{ ref('stg_lpos__case_event') }} where copies_received > 1
