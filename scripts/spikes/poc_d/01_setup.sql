-- Scratch datasets and test data for spikes 1-3. Run as yourself: python run_as.py 01_setup.sql
-- Tables expire after 3 days in case teardown is forgotten.
--
-- Tenant ids and stores follow specs.md section 3:
--   ACC-1001 tenant A (4 alerts a day), ACC-1002 tenant B (2 a day),
--   ACC-2001 vendor (1 a day, no tenant may see it), NULL no CRM record (1 a day, internal only).
-- 10 days, 2026-11-01 to 2026-11-10, so fct_alert has 40 + 20 + 10 + 10 = 80 rows.

CREATE SCHEMA IF NOT EXISTS `${PROJECT}.spike_rls`
OPTIONS (location = '${LOCATION}', default_table_expiration_days = 3,
         labels = [('poc', 'phase2'), ('owner', 'dev2'), ('purpose', 'spike')]);

CREATE SCHEMA IF NOT EXISTS `${PROJECT}.spike_rls_sec`
OPTIONS (location = '${LOCATION}', default_table_expiration_days = 3,
         labels = [('poc', 'phase2'), ('owner', 'dev2'), ('purpose', 'spike')]);

-- The published fact: partitioned, filter required, clustered on tenant first (as wh_{env}).
CREATE OR REPLACE TABLE `${PROJECT}.spike_rls.fct_alert` (
  tenant_id   STRING,
  store_id    STRING,
  incident_id STRING,
  alert_date  DATE,
  priority    STRING
)
PARTITION BY alert_date
CLUSTER BY tenant_id, store_id
OPTIONS (require_partition_filter = TRUE);

INSERT INTO `${PROJECT}.spike_rls.fct_alert`
WITH tenants AS (
  SELECT * FROM UNNEST([
    STRUCT('ACC-1001' AS tenant_id, 'S101' AS store_id, 4 AS per_day),
    STRUCT('ACC-1002', 'S103', 2),
    STRUCT('ACC-2001', 'S137', 1),
    STRUCT(CAST(NULL AS STRING), 'S136', 1)
  ])
)
SELECT t.tenant_id, t.store_id,
       FORMAT('INC-%s-%s-%d', t.store_id, FORMAT_DATE('%m%d', d), n) AS incident_id,
       d AS alert_date, 'P3' AS priority
FROM tenants AS t
CROSS JOIN UNNEST(GENERATE_DATE_ARRAY('2026-11-01', '2026-11-10')) AS d
CROSS JOIN UNNEST(GENERATE_ARRAY(1, t.per_day)) AS n;

-- What a dbt build would hand to publish (spike 2): the same rows, but 2026-11-03 and 2026-11-04 changed.
CREATE OR REPLACE TABLE `${PROJECT}.spike_rls.fct_alert_build` AS
SELECT * REPLACE (IF(alert_date IN ('2026-11-03', '2026-11-04'), 'P1', priority) AS priority)
FROM `${PROJECT}.spike_rls.fct_alert`
WHERE alert_date >= '2026-01-01';

-- A dimension: not partitioned, replaced in full on publish.
CREATE OR REPLACE TABLE `${PROJECT}.spike_rls.dim_store` AS
SELECT * FROM UNNEST([
  STRUCT('ACC-1001' AS tenant_id, 'S101' AS store_id, 'ALPHA FOODS 101' AS store_name),
  STRUCT('ACC-1002', 'S103', 'BETA FRESH 103'),
  STRUCT('ACC-2001', 'S137', 'ALPHA FOODS 137'),
  STRUCT(CAST(NULL AS STRING), 'S136', 'BETA FRESH 136')
]);

CREATE OR REPLACE TABLE `${PROJECT}.spike_rls.dim_store_build` AS
SELECT * REPLACE (CONCAT(store_name, ' (v2)') AS store_name) FROM `${PROJECT}.spike_rls.dim_store`;

-- The mapping, in a dataset the readers can't read.
CREATE OR REPLACE TABLE `${PROJECT}.spike_rls_sec.map_tenant_access` AS
SELECT * FROM UNNEST([
  STRUCT('${SA_READER_A}' AS principal, 'ACC-1001' AS tenant_id),
  STRUCT('${SA_READER_B}', 'ACC-1002')
]);

-- Dataset grants. Readers: spike_rls only. Writer: both datasets.
GRANT `roles/bigquery.dataViewer` ON SCHEMA `${PROJECT}.spike_rls`
TO "serviceAccount:${SA_READER_A}", "serviceAccount:${SA_READER_B}", "serviceAccount:${SA_MASKED}";

GRANT `roles/bigquery.dataEditor` ON SCHEMA `${PROJECT}.spike_rls` TO "serviceAccount:${SA_WRITER}";
GRANT `roles/bigquery.dataEditor` ON SCHEMA `${PROJECT}.spike_rls_sec` TO "serviceAccount:${SA_WRITER}";

SELECT 'setup done' AS status,
       (SELECT COUNT(*) FROM `${PROJECT}.spike_rls.fct_alert` WHERE alert_date >= '2026-01-01') AS fct_rows,
       (SELECT COUNT(*) FROM `${PROJECT}.spike_rls_sec.map_tenant_access`) AS mapping_rows;
