{# Newest full row per key, plus delete flag. Check field names against docs/poc2/cdc.md (A4). #}
{% macro cdc_current_state(source_relation, key_columns) %}
{%- set keys = key_columns | join(', ') -%}
with changes as (
  select
    t.* except (datastream_metadata),
    timestamp_millis(t.datastream_metadata.source_timestamp) as _source_updated_at,
    t.datastream_metadata.change_type = 'DELETE'             as _is_delete,
    t.datastream_metadata.change_sequence_number             as _seq
  from {{ source_relation }} as t
),
latest_change as (
  select {{ keys }}, _is_delete as is_deleted, _source_updated_at
  from changes
  qualify row_number() over (partition by {{ keys }} order by _source_updated_at desc, _seq desc) = 1
),
latest_image as (
  select * except (_is_delete, _source_updated_at, _seq)
  from changes
  where not _is_delete
  qualify row_number() over (partition by {{ keys }} order by _source_updated_at desc, _seq desc) = 1
)
select
  i.* except (updated_at),
  c.is_deleted,
  if(c.is_deleted, c._source_updated_at, null) as deleted_at,
  c._source_updated_at
from latest_change as c
join latest_image as i using ({{ keys }})
{% endmacro %}
