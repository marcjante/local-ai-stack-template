"""Database engine and lifecycle helpers."""

from __future__ import annotations

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


def get_session():
    with Session(engine) as session:
        yield session
