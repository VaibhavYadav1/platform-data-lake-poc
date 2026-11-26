{# C7 review step: append one row per test of this run to ops_{env}.dq_result, so failures can be followed
   over time (dq_{env} only holds the failing rows of the latest run). Called from on-run-end.
   The same table holds the DQ39 counts written by the daily full load (plan E6). #}
{% macro log_dq_results(results) %}
  {% if not execute %}{{ return('') }}{% endif %}
  {% set tests = results | selectattr('node.resource_type', 'equalto', 'test') | list %}
  {% if tests | length == 0 %}{{ return('') }}{% endif %}
  {% set target_dataset = '`' ~ target.project ~ '`.`' ~ generate_schema_name('ops', none) ~ '`' %}
  {% set target_table = target_dataset ~ '.dq_result' %}
  {# ops_{env} exists for dev and int (Terraform); local and CI runs write to their own dbt_*_ops dataset, which
     does not exist yet, and a failing on-run-end hook would fail the whole run. #}
  {% do run_query("create schema if not exists " ~ target_dataset ~ " options (location = '" ~ target.location ~ "')") %}
  {% set create %}
    create table if not exists {{ target_table }} (
      invocation_id     string,
      run_started_at    timestamp,
      test_name         string,
      test_unique_id    string,
      severity          string,
      status            string,
      failures          int64,
      failures_relation string,
      execution_seconds float64,
      logged_at         timestamp
    )
    partition by date(run_started_at)
  {% endset %}
  {% do run_query(create) %}
  {% set rows = [] %}
  {% for r in tests %}
    {% set rel = r.node.relation_name %}   {# set when the test stores its failing rows #}
    {% do rows.append(
      "('" ~ invocation_id ~ "', timestamp('" ~ run_started_at.strftime('%Y-%m-%d %H:%M:%S') ~ "'), '"
      ~ r.node.name | replace("'", "\'") ~ "', '" ~ r.node.unique_id | replace("'", "\'") ~ "', '"
      ~ (r.node.config.severity | upper) ~ "', '" ~ r.status ~ "', "
      ~ (r.failures if r.failures is not none else 'null') ~ ", "
      ~ ("'" ~ (rel | replace('`', '')) ~ "'" if rel else 'null') ~ ", "
      ~ (r.execution_time | round(3)) ~ ", current_timestamp())"
    ) %}
  {% endfor %}
  {% set insert %}
    insert into {{ target_table }}
      (invocation_id, run_started_at, test_name, test_unique_id, severity, status, failures,
       failures_relation, execution_seconds, logged_at)
    values {{ rows | join(',\n') }}
  {% endset %}
  {% do run_query(insert) %}
  {{ return('') }}
{% endmacro %}
