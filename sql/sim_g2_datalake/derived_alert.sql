-- sim_g2_datalake.derived_alert: hourly scheduled query (task A9, Terraform: module sim_g2_datalake).
-- Data Transfer Service scheduled query, destination table derived_alert, write preference WRITE_APPEND, runs as a
-- service account. Appends the previous clock hour: a wheel with 3 or more distinct EXIT_ATTEMPT events becomes
-- one alert row. @run_time is the scheduled run time. Dataset-qualified names resolve in the project the query runs in.
-- Re-running the same hour adds nothing: the NOT EXISTS keeps derived_alert_id unique.
INSERT INTO `sim_g2_datalake.derived_alert`
  (derived_alert_id, wheel_id, g2_store_id, alert_type, window_start, window_end, exit_attempt_count, created_at)
WITH win AS (
  SELECT TIMESTAMP_SUB(TIMESTAMP_TRUNC(@run_time, HOUR), INTERVAL 1 HOUR) AS window_start,
         TIMESTAMP_TRUNC(@run_time, HOUR) AS window_end
),
hits AS (
  SELECT e.wheel_id, w.window_start, w.window_end, COUNT(DISTINCT e.event_id) AS exit_attempt_count
  FROM `sim_g2_datalake.wheel_event` AS e
  CROSS JOIN win AS w
  WHERE e.event_type = 'EXIT_ATTEMPT'
    AND e.event_ts >= w.window_start AND e.event_ts < w.window_end
  GROUP BY e.wheel_id, w.window_start, w.window_end
  HAVING COUNT(DISTINCT e.event_id) >= 3
)
SELECT
  CONCAT(h.wheel_id, '-', FORMAT_TIMESTAMP('%Y%m%dT%H', h.window_start)),
  h.wheel_id,
  wh.g2_store_id,            -- NULL for an unknown wheel (DQ43)
  'CART_EXIT_ATTEMPTS',
  h.window_start,
  h.window_end,
  h.exit_attempt_count,
  @run_time
FROM hits AS h
LEFT JOIN `sim_g2_datalake.wheel` AS wh USING (wheel_id)
WHERE NOT EXISTS (
  SELECT 1 FROM `sim_g2_datalake.derived_alert` AS d
  WHERE d.derived_alert_id = CONCAT(h.wheel_id, '-', FORMAT_TIMESTAMP('%Y%m%dT%H', h.window_start))
);
