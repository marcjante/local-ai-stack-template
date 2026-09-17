"""Environment-driven settings for the isolated HC Palau application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_URL = f"sqlite:///{APP_ROOT / 'hcpalau.db'}"
DEFAULT_VIDEO_DIR = APP_ROOT / "uploads" / "exercises"


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_token: str
    cors_origins: tuple[str, ...]
    video_dir: Path


def validate_runtime_settings(settings: Settings) -> None:
    """Fail fast on unsafe defaults when running against managed infrastructure."""
    if settings.database_url.startswith("sqlite"):
        return
    if settings.admin_token == "dev-admin-token":
        raise RuntimeError("ADMIN_TOKEN must be configured when using a non-SQLite database")
    if "*" in settings.cors_origins:
        raise RuntimeError("CORS_ORIGINS must not contain '*' in managed deployments")


def get_settings() -> Settings:
    origins = os.getenv("HCPALAU_CORS_ORIGINS") or os.getenv("CORS_ORIGINS") or (
        "http://localhost:8000,http://127.0.0.1:8000"
    )
    return Settings(
        database_url=(
            os.getenv("HCPALAU_DATABASE_URL")
            or os.getenv("DATABASE_URL")
            or DEFAULT_DATABASE_URL
        ),
        admin_token=(
            os.getenv("HCPALAU_ADMIN_TOKEN")
            or os.getenv("ADMIN_TOKEN")
            or "dev-admin-token"
        ),
        cors_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
        video_dir=Path(
            os.getenv("HCPALAU_VIDEO_DIR")
            or os.getenv("VIDEO_DIR")
            or str(DEFAULT_VIDEO_DIR)
        ),
    )
