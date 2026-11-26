{# Lineage columns on every published table (section 4.6). #}
{% macro lineage_columns(source_system, source_updated_at='cast(null as timestamp)') -%}
  '{{ source_system }}'            as _source_system,
  {{ source_updated_at }}          as _source_updated_at,
  current_timestamp()              as _dbt_loaded_at,
  '{{ invocation_id }}'            as _dbt_invocation_id
{%- endmacro %}
