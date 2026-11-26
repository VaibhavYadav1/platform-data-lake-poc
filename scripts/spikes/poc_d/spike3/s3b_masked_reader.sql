-- Spike 3b. Run as spike-masked (dataset viewer + masked reader, no fine-grained reader).
-- Expect, if masking is available: ok, with SHA-256 hashes instead of names and emails.
-- Expect, if it isn't (no data policy was created): denied.
SELECT account_id, primary_contact_name, primary_contact_email
FROM `${PROJECT}.spike_rls.account_contact`
ORDER BY account_id;
