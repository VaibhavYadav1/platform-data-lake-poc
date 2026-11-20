{# A11: filter for incremental facts.
   - lookback: only rows changed since (max _source_updated_at in this table) minus the lookback window
   - guard: never replace a row with an older change than the one already stored #}
{% macro incremental_filter(key_column, updated_col='_source_updated_at') -%}
  {% if is_incremental() -%}
  where {{ updated_col }} >= timestamp_sub(
          (select coalesce(max({{ updated_col }}), timestamp '1970-01-01') from {{ this }}),
          interval {{ var('incremental_lookback_minutes') }} minute)
    and not exists (
          select 1 from {{ this }} as t
          where t.{{ key_column }} = src.{{ key_column }}
            and t.{{ updated_col }} > src.{{ updated_col }})
  {%- endif %}
{%- endmacro %}
