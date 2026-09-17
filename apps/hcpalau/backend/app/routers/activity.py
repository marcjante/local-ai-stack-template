"""Recent player actions for the coaching dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..auth import Principal, require_admin
from ..database import get_session
from ..models import Attendance, Event, Exercise, ExerciseAssignment, ExerciseProgress, Player


router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("")
def recent_activity(
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> list[dict]:
    items: list[dict] = []
    for attendance, player, event in session.exec(
        select(Attendance, Player, Event)
        .join(Player, Player.id == Attendance.player_id)
        .join(Event, Event.id == Attendance.event_id)
        .order_by(Attendance.updated_at.desc())
        .limit(20)
    ):
        items.append({"kind": "attendance", "player": player.name, "label": event.title, "value": attendance.attending, "reason": attendance.absence_reason, "updated_at": attendance.updated_at})
    for progress, player, exercise in session.exec(
        select(ExerciseProgress, Player, Exercise)
        .join(ExerciseAssignment, ExerciseAssignment.id == ExerciseProgress.assignment_id)
        .join(Player, Player.id == ExerciseAssignment.player_id)
        .join(Exercise, Exercise.id == ExerciseAssignment.exercise_id)
        .order_by(ExerciseProgress.updated_at.desc())
        .limit(20)
    ):
        items.append({"kind": "progress", "player": player.name, "label": exercise.title, "value": progress.repetitions, "updated_at": progress.updated_at})
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)[:20]
