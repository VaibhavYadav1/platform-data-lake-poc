-- Spike 3f, step 2. Run as reader A. Expect: denied (the snapshot kept the policy tags).
SELECT account_id, primary_contact_email
FROM `${PROJECT}.spike_rls.account_contact_snap`;
