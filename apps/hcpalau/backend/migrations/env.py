"""Alembic environment for the isolated HC Palau app."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import context

APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.database import build_engine  # noqa: E402
from backend.app.models import SQLModel  # noqa: E402


config = context.config
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = build_engine(get_settings().database_url)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
