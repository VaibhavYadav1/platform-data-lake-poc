-- Spike 2f (optional, about 10 minutes). Run as yourself. What happens if the writer is NOT in rls_all_rows?
-- The plan says it then sees zero rows; this checks what that does to a publish.
-- Step 1 (this file, as yourself): take the writer out of rls_all_rows on fct_alert.
-- Step 2: run s2a as the writer with --param dates=DATE[]:2026-11-05  and record the result.
--         Then run s2b as yourself: did the 2026-11-05 rows get deleted, doubled, or left alone?
-- Step 3: run s2f_restore.sql as yourself.
CREATE OR REPLACE ROW ACCESS POLICY rls_all_rows
ON `${PROJECT}.spike_rls.fct_alert`
GRANT TO ("user:${ME}")
FILTER USING (TRUE);

SELECT 'writer removed from rls_all_rows on fct_alert' AS status;
