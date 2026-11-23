{{ config(tags=['dq41_value_scan']) }}
-- DQ41, value part (error): no email-like value in any text column of the build dataset.
-- The column-name part is dq41_no_personal_data_columns. Free text (fct_alert_history.comments) is the main risk.
-- Columns in var pii_value_scan_allow hold emails by design (map_tenant_access.principal, decision 3) and are skipped.
-- It reads every text column, so the daily full load runs it (plan E6 step 5); the micro-batch may skip it with
-- --exclude tag:dq41_value_scan.
{% set allow = var('pii_value_scan_allow') %}
{% set email_regex = "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}" %}
{% set cols = [] %}
{% if execute %}
  {% set q %}
    select table_name, column_name
    from `{{ target.project }}`.`{{ generate_schema_name('build', none) }}`.INFORMATION_SCHEMA.COLUMNS
    where data_type = 'STRING'
  {% endset %}
  {% for row in run_query(q) %}
    {% if (row['table_name'] ~ '.' ~ row['column_name']) not in allow %}
      {% do cols.append(row) %}
    {% endif %}
  {% endfor %}
{% endif %}
{% if cols | length == 0 %}
select cast(null as string) as table_name, cast(null as string) as column_name, 0 as email_like_rows
from unnest([1]) where false
{% else %}
{% for c in cols %}
select '{{ c['table_name'] }}' as table_name, '{{ c['column_name'] }}' as column_name, count(*) as email_like_rows
from `{{ target.project }}`.`{{ generate_schema_name('build', none) }}`.`{{ c['table_name'] }}`
where regexp_contains(`{{ c['column_name'] }}`, r'{{ email_regex }}')
having count(*) > 0
{% if not loop.last %}union all{% endif %}
{% endfor %}
{% endif %}
