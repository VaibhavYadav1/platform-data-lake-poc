-- The two policies from plan D4, on both test tables. Run as yourself: python run_as.py 02_policies.sql
-- You are in rls_all_rows so you can check counts; in the real design only the writer and internal identities are.

CREATE OR REPLACE ROW ACCESS POLICY rls_all_rows
ON `${PROJECT}.spike_rls.fct_alert`
GRANT TO ("user:${ME}", "serviceAccount:${SA_WRITER}")
FILTER USING (TRUE);

CREATE OR REPLACE ROW ACCESS POLICY rls_tenant
ON `${PROJECT}.spike_rls.fct_alert`
GRANT TO ("serviceAccount:${SA_READER_A}", "serviceAccount:${SA_READER_B}")
FILTER USING (tenant_id IN (
  SELECT tenant_id
  FROM `${PROJECT}.spike_rls_sec.map_tenant_access`
  WHERE principal = SESSION_USER()
));

CREATE OR REPLACE ROW ACCESS POLICY rls_all_rows
ON `${PROJECT}.spike_rls.dim_store`
GRANT TO ("user:${ME}", "serviceAccount:${SA_WRITER}")
FILTER USING (TRUE);

CREATE OR REPLACE ROW ACCESS POLICY rls_tenant
ON `${PROJECT}.spike_rls.dim_store`
GRANT TO ("serviceAccount:${SA_READER_A}", "serviceAccount:${SA_READER_B}")
FILTER USING (tenant_id IN (
  SELECT tenant_id
  FROM `${PROJECT}.spike_rls_sec.map_tenant_access`
  WHERE principal = SESSION_USER()
));

SELECT 'policies created; list them with: bq ls --row_access_policies ${PROJECT}:spike_rls.fct_alert' AS status;
