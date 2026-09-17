"""Initial persistence model shared by the upcoming API tickets."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Player(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True, max_length=64)
    name: str = Field(max_length=120)
    access_token: str = Field(index=True, unique=True, max_length=255)
    access_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=160)
    starts_at: datetime = Field(index=True)
    event_type: str = Field(max_length=32)
    location: Optional[str] = Field(default=None, max_length=200)
    created_at: datetime = Field(default_factory=utc_now)


class Attendance(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("event_id", "player_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    attending: bool
    updated_at: datetime = Field(default_factory=utc_now)


class Goal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    title: str = Field(max_length=160)
    description: Optional[str] = Field(default=None, max_length=1000)
    done: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    done_at: Optional[datetime] = None
