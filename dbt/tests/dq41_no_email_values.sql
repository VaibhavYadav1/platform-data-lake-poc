{{ config(tags=['dq41_value_scan']) }}
-- DQ41, value part (error): no email-like value in any text column of the build dataset.
-- The column-name part is dq41_no_personal_data_columns. Free text (fct_alert_history.comments) is the main risk.
-- Columns listed in var pii_value_scan_allow hold emails by design and are skipped (none today: map_tenant_access stores hashes).
-- It reads every text column, so the daily full load runs it (plan E6 step 5); the micro-batch may skip it with
-- --exclude tag:dq41_value_scan.
-- The scan reads build through INFORMATION_SCHEMA, which dbt cannot see as a dependency. Without the lines
-- below it runs at the start of dbt build, scans the previous run's tables, and lets this run's emails through
-- to publish. Add any new build model here.
-- depends_on: {{ ref('dim_account') }}
-- depends_on: {{ ref('dim_alert_type') }}
-- depends_on: {{ ref('dim_date') }}
-- depends_on: {{ ref('dim_device') }}
-- depends_on: {{ ref('dim_offender') }}
-- depends_on: {{ ref('dim_store') }}
-- depends_on: {{ ref('dim_wheel') }}
-- depends_on: {{ ref('fct_alert') }}
-- depends_on: {{ ref('fct_alert_history') }}
-- depends_on: {{ ref('fct_case') }}
-- depends_on: {{ ref('fct_wheel_event') }}
-- depends_on: {{ ref('fct_work_order') }}
-- depends_on: {{ ref('map_tenant_access') }}
-- depends_on: {{ ref('mv_alert_trend_daily') }}
-- depends_on: {{ ref('mv_alert_trend_weekly') }}
-- depends_on: {{ ref('mv_cart_count_daily') }}
-- depends_on: {{ ref('mv_current_issues') }}
-- depends_on: {{ ref('mv_downtime_interval') }}
-- depends_on: {{ ref('mv_incident_health') }}
-- depends_on: {{ ref('mv_store_health') }}
-- depends_on: {{ ref('status') }}
{% set allow = var('pii_value_scan_allow') %}
{% set email_regex = "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}" %}
{% set cols = [] %}
{% set build_schema = generate_schema_name('build', none) %}
{% set build_exists = false %}
{% if execute %}
  {# In a new environment the build dataset doesn't exist until the first build; reading its column list would
     then fail `dbt compile` and `dbt build --select` of unrelated nodes. No dataset means nothing to scan. #}
  {% set found = run_query("select count(*) from `" ~ target.project ~ "`.`region-" ~ target.location | lower
                           ~ "`.INFORMATION_SCHEMA.SCHEMATA where schema_name = '" ~ build_schema ~ "'") %}
  {% set build_exists = found.columns[0].values()[0] > 0 %}
{% endif %}
{% if build_exists %}
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
