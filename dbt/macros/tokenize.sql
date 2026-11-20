{# Keyed hash of a personal value. The key lives in keys.token_key (C9). #}
{% macro tokenize(expr) -%}
  to_hex(sha256(concat(
    (select key from `{{ target.project }}.keys.token_key`), '|', cast({{ expr }} as string)
  )))
{%- endmacro %}
