{{ config(materialized='incremental', incremental_strategy='merge', unique_key='crm_store_id') }}
-- Latest version of each store, kept by a watermark merge so only changed rows are rewritten (B4).
select *
from {{ ref('stg_crm__store') }}
{% if is_incremental() %}
where updated_at > (select max(updated_at) from {{ this }})
{% endif %}
qualify row_number() over (partition by crm_store_id order by export_ts desc, updated_at desc) = 1
