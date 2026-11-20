select
  {{ dbt_utils.generate_surrogate_key(['a.account_id']) }}                      as account_key,
  a.account_id,
  t.tenant_id,                                                                  -- null when the hierarchy is broken (DQ45)
  a.account_name,
  a.customer_type_code,
  coalesce(m.customer_type_enum, 'UNKNOWN')                                     as customer_type_enum,  -- DQ36
  coalesce(m.customer_type_name, 'Unknown')                                     as customer_type_name,
  {{ is_customer("coalesce(m.customer_type_enum, 'UNKNOWN')", 'a.status') }}    as is_customer,
  a.status,
  a.parent_account_id,
  a.primary_contact_token,
  {{ lineage_columns('crm', 'a.updated_at') }}
from {{ ref('int_crm__account') }} as a
left join {{ ref('map_customer_type') }}   as m on m.customer_type_code = a.customer_type_code
left join {{ ref('int_account__tenant') }} as t on t.account_id = a.account_id
