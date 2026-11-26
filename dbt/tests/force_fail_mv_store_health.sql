{#
  E11: a test that fails only when asked to, to prove a failure in the middle of the build never
  reaches wh_dev.

    dbt build --vars '{force_fail: true}'     -> this test fails
    dbt build                                 -> this test passes (it returns no rows)

  A singular test passes when it returns no rows and fails when it returns any. It depends on
  mv_store_health, which sits in the middle of the graph: dbt builds the models upstream of it
  first (so some build_<env> tables have already changed), runs this test, and skips everything
  downstream once it fails. dbt then exits non-zero, entrypoint.sh does not call publish.py, and
  wh_<env> must be exactly as it was.

  It does not read mv_store_health's rows, so an empty table cannot make the forced failure pass.
#}
-- depends_on: {{ ref('mv_store_health') }}

{% if var('force_fail', false) %}
select 'force_fail is set: this failure is the E11 test, not a data problem' as reason
{% else %}
select 'force_fail is not set' as reason
limit 0
{% endif %}
