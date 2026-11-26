-- Spike 1a. Run as reader A, then reader B.
-- Expect: one tenant only. Reader A sees ACC-1001 with 40 rows; reader B sees ACC-1002 with 20.
-- No ACC-2001 (vendor) and no NULL tenant rows.
-- If this is refused (accessDenied on map_tenant_access), the answer to spike 1 is "no": go to s1f.
SELECT SESSION_USER() AS session_user, tenant_id, COUNT(*) AS alerts
FROM `${PROJECT}.spike_rls.fct_alert`
WHERE alert_date BETWEEN '2026-11-01' AND '2026-11-10'
GROUP BY tenant_id
ORDER BY tenant_id;
