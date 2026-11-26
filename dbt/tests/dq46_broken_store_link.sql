{{ config(severity='warn') }}
-- DQ46 (warning): CRM store points at an unknown account, or a G2 store has more than one Active CRM record.
select store_id, tenant_reason from {{ ref('int_store__tenant') }}
where tenant_reason in ('UNKNOWN_ACCOUNT', 'MULTIPLE_ACTIVE_RECORDS')
