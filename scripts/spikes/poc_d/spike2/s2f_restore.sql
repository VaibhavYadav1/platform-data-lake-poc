-- Spike 2f, restore. Run as yourself.
CREATE OR REPLACE ROW ACCESS POLICY rls_all_rows
ON `${PROJECT}.spike_rls.fct_alert`
GRANT TO ("user:${ME}", "serviceAccount:${SA_WRITER}")
FILTER USING (TRUE);

SELECT 'writer back in rls_all_rows' AS status;
