-- DQ41: fails if any column in the build dataset has a deny-listed name.
-- Names such as store_name are not on the deny list, so they pass.
{% set deny = var('pii_deny_columns') %}
select table_name, column_name
from `{{ target.project }}`.`{{ generate_schema_name('build', none) }}`.INFORMATION_SCHEMA.COLUMNS
where lower(column_name) in (
  {%- for c in deny %}'{{ c }}'{{ ',' if not loop.last }}{% endfor -%}
)
