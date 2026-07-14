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

    # Folder the route catalogue file is read from.
    shared_dir: Path = _DEFAULT_SHARED_DIR

    # Fixed upstream for the forecast slice (SECURITY.md: the only host the API
    # calls out to; never derived from request input).
    open_meteo_base_url: str = "https://api.open-meteo.com"
