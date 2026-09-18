"""Database engine and lifecycle helpers."""

from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from .config import get_settings


def build_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine_args = {"connect_args": connect_args}
    if url in {"sqlite://", "sqlite:///:memory:"}:
        engine_args["poolclass"] = StaticPool
    return create_engine(url, **engine_args)


engine = build_engine()


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    # Keep existing SQLite deployments compatible when nullable fields are
    # added. Fresh databases get these columns through SQLModel metadata;
    # ALTER is intentionally best-effort for already-created tables.
    with engine.begin() as connection:
        try:
            connection.execute(text("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS absence_reason VARCHAR(500)"))
        except Exception:
            # The column already exists (or the table is managed by a migration).
            pass
        try:
            connection.execute(text("ALTER TABLE event ADD COLUMN IF NOT EXISTS team_id INTEGER"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_event_team_id ON event (team_id)"))
        except Exception:
            pass
        try:
            connection.execute(text("ALTER TABLE team ADD COLUMN IF NOT EXISTS admin_token VARCHAR(255)"))
        except Exception:
            pass


def get_session():
    with Session(engine) as session:
        yield session
