{#
  freshness_check (E7). Run as:  dbt run-operation freshness_check --target <env>

  For every entity in the entity_registry seed that micro-batch checks, measure
  age = now - the newest ts_column in measured_on, and compare it with the promise.

    - one row per entity goes to ops_<env>.freshness_result (created if missing);
    - each breach prints one JSON line with severity ERROR and event freshness_breach. Cloud Run
      sends stdout JSON to Cloud Logging, and a log-based metric on that event drives the alert.

  A breach does not fail the run: the alert is the signal, and a stale source must not stop the
  build that may fix it. An empty table, or no row in the window, counts as a breach (age unknown).

  measured_on is <layer>.<table>. wh, sec, build and ops get the environment appended; the raw_*
  datasets are shared by every environment and used as written.
#}
{% macro freshness_check() %}
  {% if not execute %}
    {{ return(none) }}
  {% endif %}

  {% set env = target.name %}
  {% set env_layers = ['wh', 'sec', 'build', 'ops'] %}
  {% set result_table = '`' ~ target.project ~ '.ops_' ~ env ~ '.freshness_result`' %}

  {% do run_query(
    'create table if not exists ' ~ result_table ~ ' ('
    ~ 'checked_at timestamp, run_id string, entity string, measured_on string, newest_ts timestamp, '
    ~ 'age_minutes float64, promise_minutes int64, breached bool'
    ~ ') partition by date(checked_at)'
  ) %}

  {% set registry = run_query(
    "select entity, measured_on, ts_column, partition_column, promise_minutes from "
    ~ ref('entity_registry') ~ " where checked_by = 'micro-batch' order by entity"
  ) %}

  {% for row in registry.rows %}
    {% set layer = row['measured_on'].split('.')[0] %}
    {% set table = row['measured_on'].split('.')[1] %}
    {% set dataset = layer ~ '_' ~ env if layer in env_layers else layer %}
    {% set partition_column = row['partition_column'] %}
    {% if partition_column is not none and partition_column | trim | length > 0 %}
      {% set window = ' where ' ~ partition_column ~ ' >= date_sub(current_date(), interval 3 day)' %}
    {% else %}
      {% set window = '' %}
    {% endif %}

    {% set measured = run_query(
      'select max(timestamp(' ~ row['ts_column'] ~ ')) as newest_ts, '
      ~ 'timestamp_diff(current_timestamp(), max(timestamp(' ~ row['ts_column'] ~ ')), second) / 60.0 as age_minutes '
      ~ 'from `' ~ target.project ~ '.' ~ dataset ~ '.' ~ table ~ '`' ~ window
    ) %}
    {% set newest = measured.rows[0]['newest_ts'] %}
    {% set age = measured.rows[0]['age_minutes'] %}
    {% set promise = row['promise_minutes'] %}
    {% set breached = age is none or age | float > promise | float %}

    {% do run_query(
      'insert into ' ~ result_table
      ~ ' (checked_at, run_id, entity, measured_on, newest_ts, age_minutes, promise_minutes, breached) values ('
      ~ 'current_timestamp(), ' ~ "'" ~ invocation_id ~ "'" ~ ', ' ~ "'" ~ row['entity'] ~ "'" ~ ', '
      ~ "'" ~ row['measured_on'] ~ "'" ~ ', '
      ~ ("timestamp('" ~ newest.isoformat() ~ "')" if newest is not none else 'cast(null as timestamp)') ~ ', '
      ~ (age | float if age is not none else 'cast(null as float64)') ~ ', '
      ~ promise | int ~ ', ' ~ ('true' if breached else 'false') ~ ')'
    ) %}

    {% if breached %}
      {% do print(tojson({
        'severity': 'ERROR',
        'event': 'freshness_breach',
        'entity': row['entity'],
        'measured_on': row['measured_on'],
        'age_minutes': (age | float | round(1)) if age is not none else none,
        'promise_minutes': promise | int,
        'run_id': invocation_id
      })) %}
    {% else %}
      {% do print(tojson({
        'severity': 'INFO',
        'event': 'freshness_ok',
        'entity': row['entity'],
        'age_minutes': age | float | round(1),
        'promise_minutes': promise | int
      })) %}
    {% endif %}
  {% endfor %}
{% endmacro %}
