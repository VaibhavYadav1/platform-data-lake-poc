{{ config(severity='warn') }}
-- DQ47 (warning): work order with an unknown account, store or device, or an account that differs from its store's.
select work_order_id, account_id, store_id, device_id from {{ ref('fct_work_order') }} where 'DQ47' in unnest(_dq_reasons)
