# terraform/modules/cloudsql_g2

**Owner:** Dev 2  
**Tasks:** 0.10, A1  
**Status:** written (A1). Called from `terraform/shared/cloudsql_g2.tf`.

Cloud SQL `poc-ops-db`, the stand-in for StorePort G2: PostgreSQL 16, `db-f1-micro` (Enterprise edition),
logical decoding on, public IP with SSL required, Datastream's static IPs as the only authorised networks.
Backups off and no deletion protection (sandbox). `activation_policy` is ignored because night-off (E8) stops
and starts the instance.

| Creates | Notes |
| --- | --- |
| Instance `poc-ops-db` | Flag `cloudsql.logical_decoding=on`, `ssl_mode=ENCRYPTED_ONLY` |
| Database `g2` | Empty; `sql/g2/schema.sql` is applied by the A2 bootstrap |
| User `postgres` | Password from `random_password`; used only by the bootstrap |
| Secrets `poc-ops-db-postgres`, `poc-ops-db-datastream`, `poc-ops-db-simulator` | `datastream_user` and `simulator_user` are created by `sql/g2/replication.sql` (A2) with these passwords |

Outputs: `instance_name`, `connection_name`, `public_ip`, `secret_ids` (names only).

The passwords are also in the Terraform state: keep the state bucket private and never print a secret.

See `GKS-POC-Phase2-detailed-plan.md` for each task's "done when".
