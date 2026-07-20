"""Runtime configuration, read from environment variables.

pydantic-settings type-checks every value when the app starts, so a bad setting
fails immediately instead of causing a confusing error later. Every field has a
safe local-dev default; production overrides them via env, so no secrets live in
the repo.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Path to the shared/ folder, found relative to this file so it works wherever
# the repo is checked out. If a server puts shared/ somewhere else, set the
# SHARED_DIR env var and this default is ignored.
_DEFAULT_SHARED_DIR = Path(__file__).resolve().parents[2] / "shared"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # CORS lets a browser page call an API on a different origin. The default
    # setup serves the app and API from one origin, so this stays empty. If the
    # frontend moves to another origin, set CORS_ALLOWED_ORIGINS to a JSON list
    # of allowed origins, never "*" (which would allow any site).
    cors_allowed_origins: list[str] = []

    # In production the CDN adds X-Origin-Verify: <this value> to every /api/*
    # request it forwards (infra/cdk/lib/sierra-safe-stack.ts). When set, the
    # API rejects requests without it, so the only cheap path to the API is
    # through the flat-rate CDN — a cost guard, not authentication (see
    # middleware.py). Unset locally, so direct requests work as always.
    origin_verify_secret: str | None = None

    # Folder the route catalogue file is read from.
    shared_dir: Path = _DEFAULT_SHARED_DIR

    # Fixed upstream for the forecast slice (SECURITY.md: the only host the API
    # calls out to; never derived from request input).
    open_meteo_base_url: str = "https://api.open-meteo.com"

    # --- Postgres, where the dbt-built crash marts live ---
    # The same POSTGRES_* variables docker-compose, the pipeline and dbt read
    # (.env.example), so one local setup serves the whole stack. A full
    # DATABASE_URL, when set, wins over the parts (same rule as the pipeline).
    database_url: str | None = None
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "app"
    postgres_password: str = "app_dev_password"
    postgres_db: str = "app"

    # Schema dbt writes marts to (warehouse/profiles.yml). Comes from settings,
    # never from a request, so it is safe to splice into SQL as an identifier.
    warehouse_schema: str = "analytics"

    @property
    def postgres_dsn(self) -> str:
        """Connection string for psycopg, from DATABASE_URL or the parts.

        connect_timeout matters: "localhost" resolves to both ::1 and
        127.0.0.1, and Docker publishes Postgres on 127.0.0.1 only. Without a
        timeout a stuck attempt on the dead address hangs the pool's worker
        forever; with one it fails over to the address that answers. It must
        stay well under the pool's 5-second acquire timeout (crashes.py), so
        the failover finishes before the waiting request gives up.
        """
        if self.database_url:
            return self.database_url
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"user={self.postgres_user} password={self.postgres_password} "
            f"dbname={self.postgres_db} connect_timeout=2"
        )
