-- Spike 3a. Run as yourself (you hold fine-grained reader). Expect: the real names and emails.
SELECT account_id, primary_contact_name, primary_contact_email
FROM `${PROJECT}.spike_rls.account_contact`
ORDER BY account_id;
