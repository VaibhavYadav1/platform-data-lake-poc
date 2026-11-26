-- Spike 3c. Run as reader A (dataset viewer, neither fine-grained reader nor masked reader).
-- Expect: denied, naming the policy tag. This is what D5 case 5 will see if spike 3 says "no".
SELECT account_id, primary_contact_email
FROM `${PROJECT}.spike_rls.account_contact`;
