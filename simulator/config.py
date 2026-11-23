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
