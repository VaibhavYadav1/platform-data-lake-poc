-- A2: logins, grants and the publication for Datastream. Run as postgres, after schema.sql.
-- :'ds_password' and :'sim_password' are psql variables; scripts/g2_bootstrap.py fills them in
-- from Secret Manager. Never write a real password into this file.
--
-- The replication slot is NOT created here: PostgreSQL refuses to create a logical slot in a
-- transaction that has already written anything, so the bootstrap creates it on its own (step 3).

-- Datastream: read-only, plus the right to read the change log.
CREATE USER datastream_user WITH LOGIN PASSWORD :'ds_password';
ALTER USER datastream_user WITH REPLICATION;
GRANT USAGE ON SCHEMA g2 TO datastream_user;
GRANT SELECT ON ALL TABLES IN SCHEMA g2 TO datastream_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA g2 GRANT SELECT ON TABLES TO datastream_user;

-- Simulator: reads and writes rows, but can't change the schema.
CREATE USER simulator_user WITH LOGIN PASSWORD :'sim_password';
GRANT USAGE ON SCHEMA g2 TO simulator_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA g2 TO simulator_user;

-- The tables whose changes Datastream may read: all 11.
CREATE PUBLICATION poc_pub FOR TABLE
  g2.brands, g2.teams, g2.statuses, g2.users, g2.alert_types, g2.stores, g2.device_locations,
  g2.alert_incidents, g2.alert_history, g2.store_access, g2.heartbeat;
