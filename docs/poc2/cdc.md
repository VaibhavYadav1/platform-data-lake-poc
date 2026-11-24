# Cdc

**Owner:** Dev 2  
**Tasks:** A4

_Datastream sections to be written in A4:_ metadata fields; what an update and a delete look like.

## Source setup (A2, 23 Nov 2026)

Applied to `poc-ops-db` by `scripts/g2_bootstrap.py` through the Auth Proxy.

| Object | State after A2 |
| --- | --- |
| `wal_level` | `logical` (flag `cloudsql.logical_decoding=on`, A1) |
| Publication `poc_pub` | All 11 `g2` tables |
| Slot `poc_slot` | `pgoutput`, logical, `active = f` until Datastream attaches; held 215 kB of WAL just after creation |
| `datastream_user` | LOGIN, REPLICATION; SELECT on every `g2` table (and future ones, by default privileges) |
| `simulator_user` | LOGIN; SELECT, INSERT, UPDATE, DELETE on every `g2` table; no REPLICATION |
| Replica identity | Default (primary key): a delete carries only the key columns |

**Slot creation rights (guide section 21, resolved):** in Cloud SQL, `postgres` couldn't create the slot at first.
The bootstrap caught the permission error, ran `ALTER ROLE postgres WITH REPLICATION`, and retried successfully.
`postgres` now has `rolreplication = t`.

**To verify in A4:** the slot existed before the seed (A3), so the seed's inserts are also in the WAL. Datastream may
deliver those rows twice: once from the backfill and once as change events. Staging keeps one row per key, so it is
harmless, but record what actually arrives.

**After the seed (A3, 24 Nov 2026):** 2,160 rows in `g2` (baseline 2,157 plus `S999`, `D999` and the `heartbeat`
row), `store_access` empty. The slot held 960 kB of WAL. Don't change G2 until the A4 parity snapshot is taken.

**WAL held by the slot** (check before A4; must stay small while nothing reads the slot):

```sql
SELECT slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS wal_held
FROM pg_replication_slots;
```

