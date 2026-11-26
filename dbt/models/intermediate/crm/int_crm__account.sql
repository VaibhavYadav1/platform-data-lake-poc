{{ config(materialized='incremental', incremental_strategy='merge', unique_key='account_id') }}
-- Latest version of each account, kept by a watermark merge so only changed rows are rewritten (B4).
select *
from {{ ref('stg_crm__account') }}
{% if is_incremental() %}
where updated_at > (select max(updated_at) from {{ this }})
{% endif %}
qualify row_number() over (partition by account_id order by export_ts desc, updated_at desc) = 1
