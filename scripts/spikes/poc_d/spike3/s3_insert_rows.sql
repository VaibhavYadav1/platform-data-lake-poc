-- Spike 3 test rows, run by s3_setup.sh as yourself. Values follow the CRM spec: role-style names, @example.com.
INSERT INTO `${PROJECT}.spike_rls.account_contact` (account_id, primary_contact_name, primary_contact_email)
VALUES ('ACC-1001', 'Account Manager 01', 'account.manager.01@example.com'),
       ('ACC-1002', 'Account Manager 02', 'account.manager.02@example.com'),
       ('ACC-2001', 'Vendor Contact 01',  'vendor.contact.01@example.com');

SELECT COUNT(*) AS rows_loaded FROM `${PROJECT}.spike_rls.account_contact`;
