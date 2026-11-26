{{ config(schema='dq', materialized='table') }}
select * from {{ ref('int_alert__validated') }} where _dq_status = 'QUARANTINE'
