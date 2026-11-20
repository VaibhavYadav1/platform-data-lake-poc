{# The run's "as of" time. Every time calculation in a mart uses it (one value per dbt invocation). #}
{% macro snapshot_ts() -%}
  timestamp('{{ run_started_at.strftime("%Y-%m-%d %H:%M:%S") }}')
{%- endmacro %}
