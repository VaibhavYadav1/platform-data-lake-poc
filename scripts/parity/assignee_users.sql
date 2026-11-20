-- Distinct assigned users must match: tokens in POC 2, user ids in POC 1. Expected: both counts are equal.
select
  (select count(distinct fk_assigned_to) from `{project}.poc1_baseline.fct_alert_incident` where fk_assigned_to is not null) as poc1_users,
  (select count(distinct assignee_token) from `{project}.dbt_{user}_build.fct_alert` where assignee_token is not null)       as poc2_tokens
