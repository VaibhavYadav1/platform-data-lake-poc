{{ config(cluster_by=['tenant_id', 'store_id']) }}
-- Applies the health rules once per incident (C5). Every other health mart reads from here.
-- Health-relevant = customer_facing alert type, category not 'Device Ok'. Deleted incidents are left out.
-- The most specific rule wins: alert type, then priority, then location class.
with base as (
  select
    a.incident_id, a.tenant_id, a.store_id, a.alert_type_id, a.alert_name, a.priority_name,
    coalesce(d.location_class, 'UNKNOWN')   as location_class,
    a.alert_time, a.resolved_time, a.is_open,
    aty.severity, aty.customer_category_name,
    a.brand, a.ultimate_parent, a.country,
    a.level_1, a.level_2, a.level_3, a.level_4, a.level_5, a.level_6, a.level_7,
    a._source_updated_at
  from {{ ref('fct_alert') }} as a
  join {{ ref('dim_alert_type') }} as aty on aty.alert_type_id = a.alert_type_id
  left join {{ ref('dim_device') }} as d  on d.device_id = a.device_id
  where not a.is_deleted
    and aty.customer_facing
    and aty.category_name != 'Device Ok'
),
ruled as (
  select b.*, r.rule_id as health_rule_id, r.status_color as health_color
  from base as b
  left join {{ ref('map_store_health_rule') }} as r
    on  (r.alert_type_id  = b.alert_type_id  or r.alert_type_id  = '*')
    and (r.priority       = b.priority_name  or r.priority       = '*')
    and (r.location_class = b.location_class or r.location_class = '*')
  qualify row_number() over (
    partition by b.incident_id
    order by (r.alert_type_id != '*') desc, (r.priority != '*') desc, (r.location_class != '*') desc
  ) = 1
)
select
  incident_id, tenant_id, store_id, alert_type_id, alert_name, priority_name, location_class,
  alert_time, resolved_time, is_open, severity, customer_category_name,
  health_color,
  health_rule_id,
  health_color is null                               as is_unclassified,
  coalesce(health_color, 'YELLOW')                   as effective_color,
  health_color = 'RED'                               as counts_as_downtime,
  case
    when lower(customer_category_name) like '%power%'                                   then 'Power'
    when lower(customer_category_name) like '%network%'
      or lower(customer_category_name) like '%connect%'                                 then 'Network'
    when lower(customer_category_name) like '%protection%'                              then 'Protection'
    when lower(customer_category_name) like '%disabled%'                                then 'Disabled'
    when lower(customer_category_name) like '%hardware%'                                then 'Hardware'
    else 'Other'
  end                                                as downtime_cause_type,
  {{ snapshot_ts() }}                                as snapshot_ts,
  brand, ultimate_parent, country, level_1, level_2, level_3, level_4, level_5, level_6, level_7,
  {{ lineage_columns('g2', '_source_updated_at') }}
from ruled
