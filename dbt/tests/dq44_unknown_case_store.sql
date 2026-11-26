{{ config(severity='warn') }}
-- DQ44 (warning): case event names a store that is not in G2. Kept and flagged.
select event_id, g2_store_id from {{ ref('stg_lpos__case_event') }} where is_unknown_store
