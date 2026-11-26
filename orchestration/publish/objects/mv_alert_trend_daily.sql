CREATE MATERIALIZED VIEW IF NOT EXISTS `{project}.wh_{env}.mv_alert_trend_daily`
PARTITION BY alert_date
CLUSTER BY tenant_id, store_id
AS
SELECT tenant_id, store_id, alert_type_id, alert_date,
       COUNT(*)                         AS incident_count,
       APPROX_COUNT_DISTINCT(alert_id)  AS distinct_alert_count
FROM `{project}.wh_{env}.fct_alert`
WHERE NOT is_deleted
GROUP BY tenant_id, store_id, alert_type_id, alert_date;
