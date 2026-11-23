-- sql/g2/schema.sql: the StorePort G2 stand-in (task 0.5). PostgreSQL 16.
-- Columns from the POC 1 stage models, with real types, an enforced primary key, id-format checks and updated_at.
-- No foreign keys and no cross-column checks: the simulator plants unknown references, future times and
-- resolved-before-opened incidents on purpose (DQ33, DQ34, DQ38).

CREATE SCHEMA IF NOT EXISTS g2;

-- One row per brand.
CREATE TABLE g2.brands (
  brand_id        TEXT        PRIMARY KEY CHECK (brand_id ~ '^B\d{2}$'),
  brand_name      TEXT,
  is_active       BOOLEAN,
  ultimate_parent TEXT,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per support team.
CREATE TABLE g2.teams (
  team_id    TEXT        PRIMARY KEY CHECK (team_id ~ '^T\d{2}$'),
  team_name  TEXT,
  is_active  BOOLEAN,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per handling status.
CREATE TABLE g2.statuses (
  status_id        TEXT        PRIMARY KEY CHECK (status_id ~ '^\d+$'),
  status_name      TEXT,
  is_closed        BOOLEAN,
  next_step_action TEXT,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per support user.
CREATE TABLE g2.users (
  user_id    TEXT        PRIMARY KEY CHECK (user_id ~ '^U\d{3}$'),
  user_name  TEXT,
  email      TEXT        CHECK (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  team_id    TEXT        CHECK (team_id ~ '^T\d{2}$'),
  is_active  BOOLEAN,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per alert type.
CREATE TABLE g2.alert_types (
  alert_type_id                TEXT        PRIMARY KEY CHECK (alert_type_id ~ '^AT\d{2}$'),
  alert_type_name              TEXT,
  description                  TEXT,
  default_priority             TEXT,
  is_active                    BOOLEAN,
  category_name                TEXT,
  customer_category_name       TEXT,
  severity                     TEXT,
  device_type                  TEXT,
  system_type                  TEXT,
  customer_facing              BOOLEAN,
  internal_alert_name          TEXT,
  not_started_next_step_action TEXT,
  updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per store.
CREATE TABLE g2.stores (
  store_id      TEXT        PRIMARY KEY CHECK (store_id ~ '^S\d{3}$'),
  store_name    TEXT,
  brand_id      TEXT        CHECK (brand_id ~ '^B\d{2}$'),
  location_name TEXT,
  department    TEXT,
  region        TEXT,
  country       TEXT,
  state         TEXT,
  district      TEXT,
  is_active     BOOLEAN,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per device, at its current store.
CREATE TABLE g2.device_locations (
  device_id           TEXT        PRIMARY KEY CHECK (device_id ~ '^D\d{3}$'),
  store_id            TEXT        CHECK (store_id ~ '^S\d{3}$'),
  installed_location  TEXT,
  main_door_indicator BOOLEAN,
  device_type         TEXT,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per alert firing; a re-fire is a new row.
CREATE TABLE g2.alert_incidents (
  incident_id      TEXT        PRIMARY KEY CHECK (incident_id ~ '^INC\d{6}$'),
  alert_id         TEXT        CHECK (alert_id ~ '^ALR-D\d{3}-AT\d{2}$'),
  store_id         TEXT        CHECK (store_id ~ '^S\d{3}$'),
  alert_type_id    TEXT        CHECK (alert_type_id ~ '^AT\d{2}$'),
  brand_id         TEXT        CHECK (brand_id ~ '^B\d{2}$'),
  assigned_user_id TEXT        CHECK (assigned_user_id ~ '^U\d{3}$'),
  device_id        TEXT        CHECK (device_id ~ '^D\d{3}$'),
  location_name    TEXT,
  next_step_action TEXT,
  created_at       TIMESTAMPTZ,
  resolved_at      TIMESTAMPTZ,
  current_status   TEXT,
  priority         TEXT,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per incident event: status change, assignment or comment.
CREATE TABLE g2.alert_history (
  history_id         TEXT        PRIMARY KEY CHECK (history_id ~ '^H\d{7}$'),
  incident_id        TEXT        CHECK (incident_id ~ '^INC\d{6}$'),
  event_timestamp    TIMESTAMPTZ,
  event_type         TEXT,
  previous_status    TEXT,
  new_status         TEXT,
  changed_by_user_id TEXT        CHECK (changed_by_user_id ~ '^U\d{3}$'),
  comments           TEXT,
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per grant: this principal may see this CRM account.
CREATE TABLE g2.store_access (
  principal      TEXT        NOT NULL CHECK (principal ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  crm_account_id TEXT        NOT NULL,
  granted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (principal, crm_account_id)
);

-- One row per source of beats.
CREATE TABLE g2.heartbeat (
  source     TEXT        PRIMARY KEY,
  beat_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- updated_at on every UPDATE.
CREATE OR REPLACE FUNCTION g2.set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['brands', 'teams', 'statuses', 'users', 'alert_types', 'stores',
                           'device_locations', 'alert_incidents', 'alert_history', 'store_access', 'heartbeat'] LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON g2.%I FOR EACH ROW EXECUTE FUNCTION g2.set_updated_at()',
                   t || '_set_updated_at', t);
  END LOOP;
END $$;
