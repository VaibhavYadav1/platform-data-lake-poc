{{ config(severity='warn') }}
-- DQ37 (warning): store with no active CRM store record. Internal-only.
select store_id from {{ ref('int_store__tenant') }} where tenant_reason = 'NO_CRM_RECORD'
