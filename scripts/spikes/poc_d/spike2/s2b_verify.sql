-- Spike 2b. Run as yourself after s2a. Expect:
--   - every tenant's 2026-11-03 and 2026-11-04 rows now have priority P1; other dates still P3;
--   - row counts unchanged (80 in total: no rows lost or doubled, including the vendor and NULL-tenant rows
--     that the writer only "sees" through rls_all_rows);
--   - dim_store names end in "(v2)";
--   - both policies still on both tables: bq ls --row_access_policies ${PROJECT}:spike_rls.fct_alert
SELECT alert_date, priority, COUNT(*) AS alerts, COUNT(DISTINCT IFNULL(tenant_id, '(null)')) AS tenants
FROM `${PROJECT}.spike_rls.fct_alert`
WHERE alert_date BETWEEN '2026-11-01' AND '2026-11-10'
GROUP BY alert_date, priority
ORDER BY alert_date;

SELECT store_id, store_name FROM `${PROJECT}.spike_rls.dim_store` ORDER BY store_id;
