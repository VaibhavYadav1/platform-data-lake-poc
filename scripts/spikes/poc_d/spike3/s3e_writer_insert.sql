-- Spike 3e. Run as the writer, which has dataEditor but NO fine-grained reader in this spike.
-- Record the result: ok or denied. It answers plan D9 step 4 early: can a loader (sa-crm-loader) or Datastream
-- write tagged columns without fine-grained reader? If denied, D2 must give those writers fine-grained reader.
INSERT INTO `${PROJECT}.spike_rls.account_contact` (account_id, primary_contact_name, primary_contact_email)
VALUES ('ACC-9999', 'Spike Writer Test', 'spike.writer@example.com');

SELECT 'insert done' AS status;
