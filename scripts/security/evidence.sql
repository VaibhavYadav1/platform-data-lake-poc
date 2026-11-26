-- D8 evidence queries for the security report (AT-27): every blocked attempt, twice (audit log + job).
-- Replace {project} and {env}; parameters: @run_id (from ops_{env}.security_test_result), @start, @end (TIMESTAMP).
--
-- The sink (Terraform audit_sink, sink poc-bq-audit, use_partitioned_tables) creates its tables on the first
-- matching entries, so they don't exist until something has been logged:
--   audit_logs.cloudaudit_googleapis_com_data_access   (reads, queries, token requests)
--   audit_logs.cloudaudit_googleapis_com_activity      (admin activity: DDL, IAM changes)
-- iamcredentials entries (case 4) arrive only if the sink filter includes iamcredentials.googleapis.com and
-- data access logs are on for IAM Credentials (design issue 3).


-- (a) Every refused call in the window, from the audit logs. status.code 7 = PERMISSION_DENIED.
SELECT
  timestamp,
  protoPayload.authenticationInfo.principalEmail AS principal,
  protoPayload.serviceName                      AS service,
  protoPayload.methodName                       AS method,
  protoPayload.resourceName                     AS resource,
  protoPayload.status.message                   AS message,
  REGEXP_EXTRACT(protoPayload.resourceName, r'jobs/([^/]+)$') AS job_id
FROM (
  SELECT timestamp, protoPayload FROM `{project}.audit_logs.cloudaudit_googleapis_com_data_access`
  UNION ALL
  SELECT timestamp, protoPayload FROM `{project}.audit_logs.cloudaudit_googleapis_com_activity`
)
WHERE timestamp BETWEEN @start AND @end
  AND protoPayload.status.code = 7
ORDER BY timestamp;


-- (b) Each D5 attempt that should be denied, matched to its job (JOBS_BY_PROJECT keeps 180 days).
--     A test row with no matching job means the request was refused before a job existed (no job user);
--     look for it in (a) instead.
SELECT
  r.case_no, r.case_name, r.identity, r.target, r.actual, r.passed, r.job_id,
  j.user_email, j.creation_time, j.error_result.reason AS job_error, j.error_result.message AS job_message
FROM `{project}.ops_{env}.security_test_result` AS r
LEFT JOIN `{project}`.`region-us-central1`.INFORMATION_SCHEMA.JOBS_BY_PROJECT AS j
  ON j.job_id = r.job_id AND j.creation_time BETWEEN @start AND @end
WHERE r.run_id = @run_id
  AND r.expected = 'denied'
ORDER BY r.case_no, r.identity, r.target;


-- (c) Case 4: refused token requests for the writer (impersonation attempts).
SELECT
  timestamp,
  protoPayload.authenticationInfo.principalEmail AS caller,
  protoPayload.resourceName                     AS target_service_account,
  protoPayload.status.message                   AS message
FROM `{project}.audit_logs.cloudaudit_googleapis_com_data_access`
WHERE timestamp BETWEEN @start AND @end
  AND protoPayload.serviceName = 'iamcredentials.googleapis.com'
  AND protoPayload.methodName LIKE '%GenerateAccessToken'
  AND protoPayload.status.code = 7
ORDER BY timestamp;


-- (d) Summary for the report: every expected-denied attempt with its proof.
SELECT
  r.case_no, r.identity, r.target, r.passed,
  j.job_id IS NOT NULL                                AS job_found,
  j.error_result.reason = 'accessDenied'               AS job_access_denied
FROM `{project}.ops_{env}.security_test_result` AS r
LEFT JOIN `{project}`.`region-us-central1`.INFORMATION_SCHEMA.JOBS_BY_PROJECT AS j
  ON j.job_id = r.job_id AND j.creation_time BETWEEN @start AND @end
WHERE r.run_id = @run_id AND r.expected = 'denied'
ORDER BY r.case_no, r.identity;
