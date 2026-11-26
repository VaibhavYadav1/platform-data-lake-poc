select
  alert_type_id,
  internal_alert_name            as alert_name,
  description                    as alert_description,
  alert_type_name                as customer_alert_name,
  category_name,
  customer_category_name,
  severity,
  device_type,
  system_type,
  customer_facing,
  default_priority,
  not_started_next_step_action,
  is_active,
  {{ lineage_columns('g2', '_source_updated_at') }}
from {{ ref('stg_g2__alert_types') }}
where not is_deleted
