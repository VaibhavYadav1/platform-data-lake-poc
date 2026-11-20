{# Store hierarchy copied from dim_store (alias given) for filtering and roll-ups. level_4..7 are spare. #}
{% macro hierarchy_columns(alias, with_country=true) -%}
  {{ alias }}.brand,
  {{ alias }}.ultimate_parent,
  {% if with_country -%}{{ alias }}.country,{%- endif %}
  {{ alias }}.level_1,
  {{ alias }}.level_2,
  {{ alias }}.level_3,
  {{ alias }}.level_4,
  {{ alias }}.level_5,
  {{ alias }}.level_6,
  {{ alias }}.level_7
{%- endmacro %}
