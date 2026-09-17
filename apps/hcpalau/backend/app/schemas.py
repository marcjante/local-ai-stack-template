"""Public API schemas; secrets are excluded from player-facing responses."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from sqlmodel import Field, SQLModel


class PlayerCreate(SQLModel):
    slug: str = Field(min_length=1, max_length=64, regex=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=120)
    access_token: str = Field(min_length=16, max_length=255)


class PlayerRead(SQLModel):
    id: int
    slug: str
    name: str
    access_active: bool
    created_at: datetime


class PlayerAdminRead(PlayerRead):
    access_token: str


class PlayerAccessUpdate(SQLModel):
    access_active: bool


class EventCreate(SQLModel):
    title: str = Field(min_length=1, max_length=160)
    starts_at: datetime
    event_type: Literal["training", "match", "meeting"]
    location: Optional[str] = Field(default=None, max_length=200)


class EventRead(EventCreate):
    id: int
    created_at: datetime


class AttendanceUpdate(SQLModel):
    attending: bool


class AttendanceRead(AttendanceUpdate):
    id: int
    event_id: int
    player_id: int
    updated_at: datetime
