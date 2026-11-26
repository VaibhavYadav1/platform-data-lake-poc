{% macro generate_schema_name(custom_schema_name, node) -%}
  {%- set layer = custom_schema_name or 'stg' -%}
  {%- if target.name in ('dev', 'int') -%}
    {{ layer }}_{{ target.name }}
  {%- else -%}
    {{ target.schema }}_{{ layer }}
  {%- endif -%}
{%- endmacro %}
