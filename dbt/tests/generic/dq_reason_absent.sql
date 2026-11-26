{# Fails (one row per incident) when a row carries the given reason in its _dq_reasons array.
   Use with severity warn: the run continues, the count shows in the run output, and the rows
   are stored in dq_{env} (store_failures). One test per reason gives one record per check. #}
{% test dq_reason_absent(model, column_name, reason) %}
select *
from {{ model }}
where '{{ reason }}' in unnest({{ column_name }})
{% endtest %}
