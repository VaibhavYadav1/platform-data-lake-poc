-- Spike 1d. Run as reader A. A dimension and a join, as a dashboard would query.
-- Expect: one row, S101 / ALPHA FOODS 101 / 40 alerts. Not S136 (NULL tenant) or S137 (vendor).
SELECT s.store_id, s.store_name, COUNT(*) AS alerts
FROM `${PROJECT}.spike_rls.fct_alert` AS f
JOIN `${PROJECT}.spike_rls.dim_store` AS s USING (store_id)
WHERE f.alert_date BETWEEN '2026-11-01' AND '2026-11-10'
GROUP BY s.store_id, s.store_name
ORDER BY s.store_id;
