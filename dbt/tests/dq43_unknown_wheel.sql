{{ config(severity='warn') }}
-- DQ43 (warning): wheel event names an unknown wheel. Kept and flagged.
select event_id, wheel_id from {{ ref('fct_wheel_event') }} where 'DQ43' in unnest(_dq_reasons)
