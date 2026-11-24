-- E6: the ops_{env} table that full_load.py writes. full_load.py runs this file at the start of
-- every run (CREATE TABLE IF NOT EXISTS), so it exists before the first DQ39 result is written.
-- Keep only CREATE TABLE IF NOT EXISTS statements here.
-- (ops_{env}.full_load_log is created by the poc-full-load workflow itself.)

-- DQ39 results: one row per fact per full load run.
CREATE TABLE IF NOT EXISTS `{project}.ops_{env}.dq_result`
(
  run_id              STRING NOT NULL,
  check_id            STRING NOT NULL,  -- 'DQ39'
  entity              STRING NOT NULL,  -- fact table name
  incremental_only    INT64,            -- rows in the clone but not in the full rebuild
  full_refresh_only   INT64,            -- rows in the full rebuild but not in the clone
  total_diff          INT64,            -- sum of the two
  checked_at          TIMESTAMP NOT NULL,
  git_sha             STRING
)
PARTITION BY DATE(checked_at)
OPTIONS (
  description = "E6, E7: data-quality check results. DQ39 (drift) from the daily full load."
);
