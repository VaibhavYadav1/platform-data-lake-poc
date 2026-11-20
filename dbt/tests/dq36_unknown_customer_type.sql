{{ config(severity='warn') }}
-- DQ36 (warning): CRM account with an unknown type code. Enum UNKNOWN, not a customer.
select account_id, customer_type_code from {{ ref('dim_account') }} where customer_type_enum = 'UNKNOWN'
