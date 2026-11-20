{# The only place that decides whether an alert is open (C8). #}
{% macro is_open_alert(resolved_at_col, is_deleted_col='is_deleted') -%}
  ({{ resolved_at_col }} is null and not {{ is_deleted_col }})
{%- endmacro %}
