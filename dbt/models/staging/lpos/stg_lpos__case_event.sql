{{
  config(
    enabled=false
  )
}}
-- Case events counted once (DQ35: copies_received > 1) and flagged when the store is unknown (DQ44).
-- DISABLED: raw_lpos dataset not yet available in this environment
with ranked as (
  select *,
         count(*)     over (partition by event_id)                                   as copies_received,
         row_number() over (partition by event_id order by publish_time, message_id) as rn
  from {{ source('raw_lpos', 'case_event') }}
)
select
  r.event_id, r.case_id, r.event_type, r.event_ts, r.g2_store_id, r.offender_token,
  r.case_status, r.loss_amount, r.items_count, r.publish_time, r.message_id, r.copies_received,
  s.store_id is null as is_unknown_store
from ranked as r
left join {{ ref('stg_g2__stores') }} as s
  on s.store_id = r.g2_store_id and not s.is_deleted
where r.rn = 1
