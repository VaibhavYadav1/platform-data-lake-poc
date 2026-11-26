# scripts/security

**Owner:** Dev 2 / Dev 5  
**Tasks:** D5, D9, C9

POC D security tests and tools. Results of every run go to `ops_{env}.security_test_result`.

## Files

| File | Task | What it does |
| --- | --- | --- |
| `test_access.py` | D5 | pytest security suite, cases 1–7 (AT-24 command line, AT-27, AT-28 case 5) |
| `checks.py` | D5 | The cases as functions; `test_access.py` calls them |
| `security_lib.py` | D5, D6 | Identities, impersonated BigQuery access, denied-vs-error classification, results table |
| `access_removal.py` | D6 | AT-25: `simulator revoke`, rows gone within 20 minutes, `simulator grant`, rows back |
| `evidence.sql` | D8 | Links each blocked attempt to its audit log entry and its job (security report) |
| `tag_raw_columns.py` | D9 | Policy tags on the Datastream tables in `raw_g2` (Terraform tags `raw_crm`) |
| `load_token_key.py` | C9 | One-time load of `keys.token_key` (not written yet) |
| `tests/` | – | Offline tests with fakes: `pytest scripts/security` (the suite itself is skipped) |

## Prerequisites

1. D2 applied: the identities of plan section 4.4, plus `sa-pii-probe`.
2. D3: `store_access` rows for the test identities; D4: both row policies on every tenant-scoped `wh_{env}` table;
   data published to `wh_{env}` and `sec_{env}`.
3. **The runner** (you, or CI) needs:
   - token creator on the test identities: Terraform variable `security_test_runners`. **Never** on `sa-dwh-writer-{env}`;
   - a place in `rls_all_rows` (the internal counts of case 1), read on `sec_{env}`, write on `ops_{env}`;
   - write on `wh_{env}` once, to create the empty canary table `zz_security_canary` that case 2 tries to change.
4. `pip install -r scripts/security/requirements.txt`, then `gcloud auth application-default login`.

## Run

```bash
export RUN_SECURITY_SUITE=1 PROJECT=gks-datalake-poc2-dev ENV=dev
pytest scripts/security/test_access.py -v                   # cases 1-6
RUN_PUBLISH_CONSISTENCY=1 pytest scripts/security/test_access.py -k case7   # during a publish (10 min)
python scripts/security/access_removal.py                   # D6; needs the micro-batch and G2 settings
python scripts/security/tag_raw_columns.py --pii-direct-tag <policy_tags output> --dry-run   # then without
```

Settings: `TENANT_A` (default `ACC00001`), `TENANT_B` (`ACC00005`), `VENDOR_ACCOUNT` (`ACC00031`),
`PROBE_STORE` (`S999`), `SEC_READABLE=1` only if spike 1 failed and readers got viewer on `sec_{env}`.

A check passes only on a real refusal (`403 accessDenied`, or IAM `PERMISSION_DENIED` for impersonation).
A syntax error or a missing table fails the check: it proves nothing.

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".
