-- Spike 1e. Run as yourself. Removes reader A's mapping (what simulator revoke + a micro-batch will do in D6).
-- Then run s1a as reader A: expect (no rows), straight away. Then run s1e_grant.sql to restore.
-- This shows the policy itself adds no delay, so AT-25's lag is the pipeline only (CDC + micro-batch).
DELETE FROM `${PROJECT}.spike_rls_sec.map_tenant_access`
WHERE principal = '${SA_READER_A}';

SELECT principal, tenant_id FROM `${PROJECT}.spike_rls_sec.map_tenant_access` ORDER BY principal;
