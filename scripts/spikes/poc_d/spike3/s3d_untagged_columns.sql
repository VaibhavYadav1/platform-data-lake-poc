-- Spike 3d. Run as reader A. Expect: ok, 3 account ids.
-- The untagged columns stay readable, so tagging doesn't break queries that don't touch personal data.
SELECT * EXCEPT (primary_contact_name, primary_contact_email)
FROM `${PROJECT}.spike_rls.account_contact`
ORDER BY account_id;
