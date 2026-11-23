# sql/g2

**Owner:** Dev 3 (schema), Dev 2 (replication)  
**Tasks:** 0.5, A2

| File | Task | What | Applied by |
| --- | --- | --- | --- |
| `schema.sql` | 0.5 | Schema `g2`, 11 tables, id-format checks, `updated_at` trigger. No foreign keys | `scripts/g2_bootstrap.py` (step 1) |
| `replication.sql` | A2 | `datastream_user` (REPLICATION, SELECT), `simulator_user` (SELECT, INSERT, UPDATE, DELETE), publication `poc_pub` on all 11 tables. Passwords are psql variables (`:'ds_password'`, `:'sim_password'`) filled in from Secret Manager | `scripts/g2_bootstrap.py` (step 2) |

The replication slot `poc_slot` is not in `replication.sql`: PostgreSQL refuses to create a logical slot in a
transaction that has already written anything, so the bootstrap creates it on its own (step 3).

Both files apply once only. Applied to Cloud SQL `poc-ops-db` on 23 Nov 2026.

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".
