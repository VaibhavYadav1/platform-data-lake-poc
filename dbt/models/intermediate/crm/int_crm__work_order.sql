{{ config(materialized='incremental', incremental_strategy='merge', unique_key='work_order_id') }}
-- Latest version of each work_order, kept by a watermark merge so only changed rows are rewritten (B4).
select *
from {{ ref('stg_crm__work_order') }}
{% if is_incremental() %}
where updated_at > (select max(updated_at) from {{ this }})
{% endif %}
qualify row_number() over (partition by work_order_id order by export_ts desc, updated_at desc) = 1
