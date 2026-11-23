{{ config(severity='warn') }}
-- AT-26b guard: golden_store_health passes trivially when the seed has no rows for this checkpoint.
-- This warns until the scenario owner fills seeds/golden_store_health.csv, so an empty seed is never read as a pass.
-- A seed file with no rows creates no BigQuery table (dbt still logs "CREATE 0" and caches it as existing),
-- so BigQuery's own table list is checked first.
{% set seed = ref('golden_store_health') %}
{% set seed_exists = true %}
{% if execute %}
  {% set found = run_query("select count(*) from `" ~ seed.database ~ "`.`" ~ seed.schema ~ "`.INFORMATION_SCHEMA.TABLES where table_name = '" ~ seed.identifier ~ "'") %}
  {% set seed_exists = found.columns[0].values()[0] > 0 %}
{% endif %}
{% if not seed_exists %}
select '{{ var('golden_step') }}' as after_step, 'golden seed table missing: the seed file has no rows' as problem
{% else %}
select '{{ var('golden_step') }}' as after_step, 'no golden scenarios for this checkpoint' as problem
from (select count(*) as n from {{ seed }} where after_step = '{{ var('golden_step') }}')
where n = 0
{% endif %}
