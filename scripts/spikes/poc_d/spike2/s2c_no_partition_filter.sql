-- Spike 2c. Run as the writer. Expect: error. A delete on the fact without a partition filter is refused,
-- so publish.py must always pass the changed dates (and the daily full publish must use a date range, not TRUE).
DELETE FROM `${PROJECT}.spike_rls.fct_alert` WHERE TRUE;
