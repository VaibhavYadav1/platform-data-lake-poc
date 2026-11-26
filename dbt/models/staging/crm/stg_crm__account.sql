-- One row per account per export. Personal data stops here: name and email are dropped, one token is kept (B4, C9).
select
  account_id,
  trim(account_name)                                       as account_name,
  customer_type_code,
  initcap(trim(status))                                    as status,
  nullif(trim(parent_account_id), '')                      as parent_account_id,
  {{ tokenize("lower(trim(primary_contact_email))") }}     as primary_contact_token,
  updated_at,
  export_ts
from {{ source('raw_crm', 'account_landing') }}
