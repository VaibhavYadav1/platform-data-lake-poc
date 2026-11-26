-- Status lookup built from G2 (decision 2), not from a seed, so the warehouse cannot drift from G2.
select
  cast(status_id as string)  as status_id,
  status_name,
  is_closed,
  next_step_action,
  {{ lineage_columns('g2', '_source_updated_at') }}
from {{ ref('stg_g2__statuses') }}
where not is_deleted
