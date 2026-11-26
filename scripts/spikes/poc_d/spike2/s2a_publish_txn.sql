-- Spike 2a. Run as the writer, with the dates this "run" changed:
--   python run_as.py spike2/s2a_publish_txn.sql --as $SA_WRITER --expect ok --param dates=DATE[]:2026-11-03,2026-11-04
-- This is the shape publish.py will generate (plan E5): a partition swap on a fact with row policies and
-- require_partition_filter, plus a full replace of a dimension, in ONE multi-statement transaction.
-- Expect: ok. Record the duration printed by run_as.py. Then run s2b as yourself.
BEGIN
  BEGIN TRANSACTION;

  DELETE FROM `${PROJECT}.spike_rls.fct_alert` WHERE alert_date IN UNNEST(@dates);
  INSERT INTO `${PROJECT}.spike_rls.fct_alert` (tenant_id, store_id, incident_id, alert_date, priority)
    SELECT tenant_id, store_id, incident_id, alert_date, priority
    FROM `${PROJECT}.spike_rls.fct_alert_build`
    WHERE alert_date IN UNNEST(@dates);

  DELETE FROM `${PROJECT}.spike_rls.dim_store` WHERE TRUE;
  INSERT INTO `${PROJECT}.spike_rls.dim_store` (tenant_id, store_id, store_name)
    SELECT tenant_id, store_id, store_name FROM `${PROJECT}.spike_rls.dim_store_build`;

  COMMIT TRANSACTION;
EXCEPTION WHEN ERROR THEN
  ROLLBACK TRANSACTION;
  RAISE USING MESSAGE = @@error.message;
END;

SELECT 'published' AS status;
