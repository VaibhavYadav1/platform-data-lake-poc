-- AT-19 check 1: every is_customer account has enum CUSTOMER and status Active (exactly the macro's rule).
select account_id, customer_type_enum, status
from {{ ref('dim_account') }}
where is_customer and not (customer_type_enum = (select customer_type_enum from {{ ref('map_customer_type') }} where counts_as_customer limit 1) and status = 'Active')
