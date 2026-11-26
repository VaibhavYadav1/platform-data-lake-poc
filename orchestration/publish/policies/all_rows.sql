-- D4: every row, for the writer and the internal analyst (plan section 9, D4).
-- The writer must be named here: a principal named in no policy sees zero rows, so the writer's own
-- post-publish row counts would read nothing.
-- publish.py fills in the project, environment, table and all-rows principals from config.<env>.yaml
-- and applies this to every table marked tenant_scoped in tables.yaml.
CREATE ROW ACCESS POLICY IF NOT EXISTS rls_all_rows
ON `{project}.wh_{env}.{table}`
GRANT TO ({all_rows_principals})
FILTER USING (TRUE);
