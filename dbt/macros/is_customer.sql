{# The only place that decides who is a customer (B6, B8). #}
{% macro is_customer(type_enum_col, status_col) -%}
  ({{ type_enum_col }} = 'CUSTOMER' and {{ status_col }} = 'Active')
{%- endmacro %}
