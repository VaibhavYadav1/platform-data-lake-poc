-- Spike 1b. Run as reader A. Expect: (no rows). Asking for tenant B's id directly returns nothing.
SELECT tenant_id, COUNT(*) AS alerts
FROM `${PROJECT}.spike_rls.fct_alert`
WHERE alert_date BETWEEN '2026-11-01' AND '2026-11-10'
  AND tenant_id IN ('ACC-1002', 'ACC-2001')
GROUP BY tenant_id;
