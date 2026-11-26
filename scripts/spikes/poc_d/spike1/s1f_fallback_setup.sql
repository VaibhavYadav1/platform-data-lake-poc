-- Spike 1f. ONLY if s1a was refused. Run as yourself. This is the plan's fallback (section 5, spike 1):
-- readers may read the mapping dataset, but a row policy limits them to their own mapping rows.
-- Then re-run s1a (expect it to work now) and s1c (expect only reader A's own row).
GRANT `roles/bigquery.dataViewer` ON SCHEMA `${PROJECT}.spike_rls_sec`
TO "serviceAccount:${SA_READER_A}", "serviceAccount:${SA_READER_B}";

-- The writer and you must keep seeing every row, or publishing and checks break.
CREATE OR REPLACE ROW ACCESS POLICY rls_all_rows
ON `${PROJECT}.spike_rls_sec.map_tenant_access`
GRANT TO ("user:${ME}", "serviceAccount:${SA_WRITER}")
FILTER USING (TRUE);

CREATE OR REPLACE ROW ACCESS POLICY rls_self
ON `${PROJECT}.spike_rls_sec.map_tenant_access`
GRANT TO ("serviceAccount:${SA_READER_A}", "serviceAccount:${SA_READER_B}")
FILTER USING (principal = SESSION_USER());

SELECT 'fallback in place' AS status;
