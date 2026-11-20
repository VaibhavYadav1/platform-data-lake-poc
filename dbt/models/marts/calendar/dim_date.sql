{{ config(tags=['daily']) }}
with d as (
  select cast(date_day as date) as date_day
  from (
    {{ dbt_utils.date_spine(datepart='day', start_date="cast('2024-01-01' as date)", end_date="cast('2028-01-01' as date)") }}
  )
)
select
  date_day,
  extract(year from date_day)                       as year,
  extract(quarter from date_day)                    as quarter,
  extract(month from date_day)                      as month,
  format_date('%B', date_day)                       as month_name,
  extract(day from date_day)                        as day_of_month,
  extract(dayofweek from date_day) - 1 + if(extract(dayofweek from date_day) = 1, 7, 0) as day_of_week,  -- ISO: 1 = Monday
  format_date('%A', date_day)                       as day_name,
  extract(isoyear from date_day)                    as iso_year,
  extract(isoweek from date_day)                    as iso_week,
  date_trunc(date_day, isoweek)                     as week_start,
  extract(dayofweek from date_day) in (1, 7)        as is_weekend,
  'generated'                                       as _source_system,
  cast(date_day as timestamp)                       as _source_updated_at,
  current_timestamp()                               as _dbt_loaded_at,
  '{{ invocation_id }}'                             as _dbt_invocation_id
from d
