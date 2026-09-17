"""Initial persistence model shared by the upcoming API tickets."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import CheckConstraint, UniqueConstraint
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
    absence_reason: Optional[str] = Field(default=None, max_length=500)
    updated_at: datetime = Field(default_factory=utc_now)


class Goal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    title: str = Field(max_length=160)
    description: Optional[str] = Field(default=None, max_length=1000)
    done: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    done_at: Optional[datetime] = None


class Exercise(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=160)
    description: Optional[str] = Field(default=None, max_length=2000)
    video_filename: Optional[str] = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=utc_now)


class ExerciseAssignment(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("exercise_id", "player_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    exercise_id: int = Field(foreign_key="exercise.id", index=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    assigned_at: datetime = Field(default_factory=utc_now)


class ExerciseProgress(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("assignment_id", "iso_year", "iso_week"),
        CheckConstraint("repetitions >= 0 AND repetitions <= 3"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    assignment_id: int = Field(foreign_key="exerciseassignment.id", index=True)
    iso_year: int
    iso_week: int
    repetitions: int = Field(default=0, ge=0, le=3)
    updated_at: datetime = Field(default_factory=utc_now)


class ExerciseCheckin(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("player_id", "exercise_id", "activity_date"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    exercise_id: int = Field(foreign_key="exercise.id", index=True)
    activity_date: date = Field(index=True)
    completed: bool
    updated_at: datetime = Field(default_factory=utc_now)


class Convocation(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("event_id", "player_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    selection_status: str = Field(max_length=32)
    note: Optional[str] = Field(default=None, max_length=500)
    updated_at: datetime = Field(default_factory=utc_now)


class Routine(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    title: str = Field(max_length=160)
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class RoutineExercise(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("routine_id", "exercise_id"),
        UniqueConstraint("routine_id", "position"),
        CheckConstraint("position >= 1"),
        CheckConstraint("target_repetitions >= 1"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    routine_id: int = Field(foreign_key="routine.id", index=True)
    exercise_id: int = Field(foreign_key="exercise.id", index=True)
    position: int = Field(ge=1)
    target_repetitions: int = Field(default=1, ge=1)


class ExamPeriod(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("player_id", "start_date", "end_date"),
        CheckConstraint("end_date >= start_date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    start_date: date = Field(index=True)
    end_date: date
    note: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)


class Standing(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("season", "team"),
        UniqueConstraint("season", "position"),
        CheckConstraint("position >= 1"),
        CheckConstraint("played >= 0 AND won >= 0 AND drawn >= 0 AND lost >= 0"),
        CheckConstraint("goals_for >= 0 AND goals_against >= 0 AND points >= 0"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    season: str = Field(index=True, max_length=32)
    team: str = Field(max_length=160)
    position: int = Field(ge=1)
    played: int = Field(default=0, ge=0)
    won: int = Field(default=0, ge=0)
    drawn: int = Field(default=0, ge=0)
    lost: int = Field(default=0, ge=0)
    goals_for: int = Field(default=0, ge=0)
    goals_against: int = Field(default=0, ge=0)
    points: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=utc_now)


class MvpRecognition(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("event_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    note: Optional[str] = Field(default=None, max_length=500)
    awarded_at: datetime = Field(default_factory=utc_now)


class FollowUp(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    observed_on: date = Field(index=True)
    category: str = Field(max_length=32)
    note: str = Field(max_length=2000)
    visible_to_player: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class Reinforcement(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("event_id", "player_name", "source_team"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    player_name: str = Field(max_length=120)
    source_team: str = Field(max_length=160)
    playing_position: str = Field(max_length=32)
    confirmed: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class PlayerStats(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("player_id", "season"),
        CheckConstraint(
            "games >= 0 AND goals >= 0 AND assists >= 0 AND yellow_cards >= 0 AND red_cards >= 0"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    season: str = Field(index=True, max_length=32)
    games: int = Field(default=0, ge=0)
    goals: int = Field(default=0, ge=0)
    assists: int = Field(default=0, ge=0)
    yellow_cards: int = Field(default=0, ge=0)
    red_cards: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=utc_now)


class PlayerStatsImport(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("player_id", "season", "source_key"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    season: str = Field(max_length=32)
    source_key: str = Field(max_length=255)
    imported_at: datetime = Field(default_factory=utc_now)
