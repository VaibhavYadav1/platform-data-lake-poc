CREATE MATERIALIZED VIEW IF NOT EXISTS `{project}.wh_{env}.mv_cart_count_daily`
PARTITION BY event_date
CLUSTER BY tenant_id, store_id
AS
SELECT tenant_id, store_id, event_date,
       COUNT(*)                             AS event_count,
       COUNTIF(event_type = 'EXIT_ATTEMPT') AS exit_attempts,
       APPROX_COUNT_DISTINCT(wheel_id)      AS active_wheels   -- COUNT(DISTINCT) is not allowed here
FROM `{project}.wh_{env}.fct_wheel_event`
GROUP BY tenant_id, store_id, event_date;
