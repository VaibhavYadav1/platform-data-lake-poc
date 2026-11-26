-- D4: each tenant user and per-tenant app identity sees only its own tenants' rows (plan section 9, D4).
-- sec_{env}.map_tenant_access holds one row per (principal, tenant) with the principal as a SHA-256 hash of the
-- lower-case email: readers must be able to read that table (spike 1), so it never holds the email itself.
-- Rows with a null tenant_id match nothing, so no tenant sees them.
-- publish.py fills in the project, environment, table and tenant principals from config.<env>.yaml.
CREATE ROW ACCESS POLICY IF NOT EXISTS rls_tenant
ON `{project}.wh_{env}.{table}`
GRANT TO ({tenant_principals})
FILTER USING (tenant_id IN (
  SELECT tenant_id
  FROM `{project}.sec_{env}.map_tenant_access`
  WHERE principal_hash = TO_HEX(SHA256(LOWER(SESSION_USER())))
));
