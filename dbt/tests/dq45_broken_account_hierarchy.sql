{{ config(severity='warn') }}
-- DQ45 (warning): the store's account has a missing parent or a loop. Tenant is null.
select store_id, account_id from {{ ref('int_store__tenant') }} where tenant_reason = 'BROKEN_HIERARCHY'
