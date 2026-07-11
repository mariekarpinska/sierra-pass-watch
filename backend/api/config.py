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

    # The API only reads (SELECT), so production points this at a read-only
    # database user. This default is the local docker-compose account. Use
    # 127.0.0.1, not "localhost", to match where docker-compose publishes it.
    database_url: str = "postgresql://app:app_dev_password@127.0.0.1:5432/app"

    # CORS lets a browser page call an API on a different origin. The default
    # setup serves the app and API from one origin, so this stays empty. If the
    # frontend moves to another origin, set CORS_ALLOWED_ORIGINS to a JSON list
    # of allowed origins, never "*" (which would allow any site).
    cors_allowed_origins: list[str] = []

    # Folder the route catalogue file is read from.
    shared_dir: Path = _DEFAULT_SHARED_DIR
