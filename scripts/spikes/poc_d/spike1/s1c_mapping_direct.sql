-- Spike 1c. Run as reader A. Expect: denied. Readers can't read the mapping table themselves.
-- (After the fallback in s1f, expect only reader A's own mapping row instead.)
SELECT principal, tenant_id
FROM `${PROJECT}.spike_rls_sec.map_tenant_access`;
