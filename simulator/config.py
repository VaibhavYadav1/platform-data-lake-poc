"""Settings from environment variables (plan 0.6). Nothing is read from files, so the Cloud Run job (A8) works the same."""

import os
from dataclasses import dataclass

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class Settings:
    host: str | None
    port: int
    db: str
    user: str
    password: str | None
    instance: str | None  # PG_INSTANCE: Cloud SQL connection name, used from A3 on
    secret: str | None  # PG_SECRET: Secret Manager name of the password, used from A3 on

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        return cls(
            host=env.get("PG_HOST"),
            port=int(env.get("PG_PORT", "5432")),
            db=env.get("PG_DB", "g2"),
            user=env.get("PG_USER", "postgres"),
            password=env.get("PG_PASSWORD"),
            instance=env.get("PG_INSTANCE"),
            secret=env.get("PG_SECRET"),
        )

    @property
    def is_local(self):
        return self.instance is None and self.host in LOCAL_HOSTS

    def describe(self):
        """Where we connect, for log lines. Never includes the password."""
        if self.instance:
            return f"Cloud SQL {self.instance}, database {self.db}, user {self.user}"
        return f"{self.host}:{self.port}, database {self.db}, user {self.user}"


# ---- sim_g2_datalake (task A9): BigQuery target of the wheel writer. Same defaults as loaders/crm/create_raw_crm.py ----
DEFAULT_LAKE_PROJECT = "gks-datalake-poc2-dev"
DEFAULT_LAKE_LOCATION = "us-central1"
DEFAULT_LAKE_DATASET = "sim_g2_datalake"  # dbt: var g2dl_dataset


@dataclass(frozen=True)
class LakeSettings:
    project: str
    dataset: str
    location: str
    raw_g2_project: str = DEFAULT_LAKE_PROJECT  # where raw_g2 (Datastream landing) lives: the stores come from there
    raw_g2_dataset: str = "raw_g2"  # dbt: var g2_raw_dataset

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        main_project = env.get("GCP_PROJECT") or DEFAULT_LAKE_PROJECT  # as dbt/profiles.yml
        return cls(
            # G2DL_PROJECT matches dbt's g2dl_project (the lake's project); otherwise the main project
            project=env.get("G2DL_PROJECT") or main_project,
            dataset=env.get("G2DL_DATASET", DEFAULT_LAKE_DATASET),
            location=env.get("G2DL_LOCATION", DEFAULT_LAKE_LOCATION),
            raw_g2_project=main_project,
            raw_g2_dataset=env.get("G2_RAW_DATASET", "raw_g2"),
        )

    def describe(self):
        return f"BigQuery {self.project}.{self.dataset} ({self.location})"
