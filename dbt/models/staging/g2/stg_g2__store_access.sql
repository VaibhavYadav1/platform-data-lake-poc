{{
  config(
    enabled=false
  )
}}
-- Current state per key from the append-only change stream (A10).
-- DISABLED: g2_store_access table not yet available in this environment
{{ cdc_current_state(source('raw_g2', 'g2_store_access'), ['principal', 'crm_account_id']) }}
