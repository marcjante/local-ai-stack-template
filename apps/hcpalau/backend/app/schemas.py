"""Public API schemas; secrets are excluded from player-facing responses."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import model_validator
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


class SessionRead(SQLModel):
    role: Literal["admin", "player"]
    player: Optional[PlayerRead] = None


class EventCreate(SQLModel):
    title: str = Field(min_length=1, max_length=160)
    starts_at: datetime
    event_type: Literal["training", "match", "meeting"]
    location: Optional[str] = Field(default=None, max_length=200)


class EventRead(EventCreate):
    id: int
    created_at: datetime


class EventTitleUpdate(SQLModel):
    title: str = Field(min_length=1, max_length=160)


class AttendanceUpdate(SQLModel):
    attending: bool
    absence_reason: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_absence_reason(self) -> "AttendanceUpdate":
        if not self.attending and not (self.absence_reason or "").strip():
            raise ValueError("absence_reason is required when attending is false")
        if self.attending:
            self.absence_reason = None
        elif self.absence_reason:
            self.absence_reason = self.absence_reason.strip()
        return self


class AttendanceRead(AttendanceUpdate):
    id: int
    event_id: int
    player_id: int
    updated_at: datetime


class GoalCreate(SQLModel):
    player_id: int
    title: str = Field(min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=1000)


class GoalRead(GoalCreate):
    id: int
    done: bool
    created_at: datetime
    done_at: Optional[datetime]


class GoalDoneUpdate(SQLModel):
    done: bool


class ExerciseCreate(SQLModel):
    title: str = Field(min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=2000)


class ExerciseRead(ExerciseCreate):
    id: int
    video_filename: Optional[str]
    created_at: datetime


class ExerciseAssignmentRead(SQLModel):
    id: int
    exercise_id: int
    player_id: int
    assigned_at: datetime


class ExerciseProgressRead(SQLModel):
    id: int
    assignment_id: int
    iso_year: int
    iso_week: int
    repetitions: int
    updated_at: datetime


class ConvocationUpdate(SQLModel):
    selection_status: Literal["selected", "reserve", "not_selected"]
    note: Optional[str] = Field(default=None, max_length=500)


class ConvocationRead(ConvocationUpdate):
    id: int
    event_id: int
    player_id: int
    updated_at: datetime


class TeamConvocationRead(SQLModel):
    player_id: int
    player_name: str


class RoutineCreate(SQLModel):
    player_id: int
    title: str = Field(min_length=1, max_length=160)


class RoutineRead(RoutineCreate):
    id: int
    active: bool
    created_at: datetime


class RoutineExerciseCreate(SQLModel):
    exercise_id: int
    position: int = Field(ge=1)
    target_repetitions: int = Field(default=1, ge=1)


class RoutineExerciseRead(RoutineExerciseCreate):
    id: int
    routine_id: int


class ExamPeriodCreate(SQLModel):
    player_id: int
    start_date: date
    end_date: date
    note: Optional[str] = Field(default=None, max_length=500)


class ExamPeriodRead(ExamPeriodCreate):
    id: int
    created_at: datetime


class StandingUpdate(SQLModel):
    season: str = Field(min_length=1, max_length=32)
    team: str = Field(min_length=1, max_length=160)
    position: int = Field(ge=1)
    played: int = Field(default=0, ge=0)
    won: int = Field(default=0, ge=0)
    drawn: int = Field(default=0, ge=0)
    lost: int = Field(default=0, ge=0)
    goals_for: int = Field(default=0, ge=0)
    goals_against: int = Field(default=0, ge=0)
    points: int = Field(default=0, ge=0)


class StandingRead(StandingUpdate):
    id: int
    updated_at: datetime


class MvpUpdate(SQLModel):
    note: Optional[str] = Field(default=None, max_length=500)


class MvpRead(MvpUpdate):
    id: int
    event_id: int
    player_id: int
    awarded_at: datetime


class FollowUpCreate(SQLModel):
    player_id: int
    observed_on: date
    category: Literal["technical", "tactical", "physical", "attitude"]
    note: str = Field(min_length=1, max_length=2000)
    visible_to_player: bool = False


class FollowUpRead(FollowUpCreate):
    id: int
    created_at: datetime


class ReinforcementCreate(SQLModel):
    event_id: int
    player_name: str = Field(min_length=1, max_length=120)
    source_team: str = Field(min_length=1, max_length=160)
    playing_position: Literal["goalkeeper", "field"]


class ReinforcementRead(ReinforcementCreate):
    id: int
    confirmed: bool
    created_at: datetime


class ReinforcementConfirmationUpdate(SQLModel):
    confirmed: bool


class PlayerStatsIncrement(SQLModel):
    season: str = Field(min_length=1, max_length=32)
    source_key: str = Field(min_length=1, max_length=255)
    games: int = Field(default=0, ge=0)
    goals: int = Field(default=0, ge=0)
    assists: int = Field(default=0, ge=0)
    yellow_cards: int = Field(default=0, ge=0)
    red_cards: int = Field(default=0, ge=0)


class PlayerStatsRead(SQLModel):
    id: int
    player_id: int
    season: str
    games: int
    goals: int
    assists: int
    yellow_cards: int
    red_cards: int
    updated_at: datetime
