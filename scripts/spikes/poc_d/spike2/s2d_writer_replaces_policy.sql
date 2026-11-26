-- Spike 2d. Run as the writer. Expect: ok.
-- Proves the custom role (spikeRlsWriter = the candidate pocDwhWriterRls) plus dataEditor is enough for
-- publish.py to own the policies (D-28), including CREATE OR REPLACE when the grantee list changes.
CREATE OR REPLACE ROW ACCESS POLICY rls_tenant
ON `${PROJECT}.spike_rls.fct_alert`
GRANT TO ("serviceAccount:${SA_READER_A}", "serviceAccount:${SA_READER_B}")
FILTER USING (tenant_id IN (
  SELECT tenant_id
  FROM `${PROJECT}.spike_rls_sec.map_tenant_access`
  WHERE principal = SESSION_USER()
));

SELECT 'policy replaced by the writer' AS status;
