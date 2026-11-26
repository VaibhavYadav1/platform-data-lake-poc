-- Spike 1e, restore. Run as yourself. Then s1a as reader A should show ACC-1001 / 40 again.
INSERT INTO `${PROJECT}.spike_rls_sec.map_tenant_access` (principal, tenant_id)
VALUES ('${SA_READER_A}', 'ACC-1001');

SELECT principal, tenant_id FROM `${PROJECT}.spike_rls_sec.map_tenant_access` ORDER BY principal;
