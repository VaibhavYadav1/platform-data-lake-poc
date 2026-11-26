-- Spike 3f, step 1. Run as yourself. Snapshot the tagged table (as A4 does for raw_g2_parity).
-- Step 2: run s3f_snapshot_read.sql as reader A. Denied means snapshots keep the tags;
-- ok with real emails means raw_g2_parity must be snapshotted only after tagging (or not hold personal columns).
CREATE SNAPSHOT TABLE IF NOT EXISTS `${PROJECT}.spike_rls.account_contact_snap`
CLONE `${PROJECT}.spike_rls.account_contact`
OPTIONS (expiration_timestamp = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 3 DAY));

SELECT 'snapshot taken' AS status;
