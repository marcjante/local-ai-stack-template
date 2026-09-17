"""Recent player actions for the coaching dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..auth import Principal, require_admin
from ..database import get_session
from ..models import Attendance, Event, Exercise, ExerciseAssignment, ExerciseCheckin, ExerciseProgress, Player


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
        items.append({"kind": "attendance", "player": player.name, "label": event.title, "value": attendance.attending, "reason": attendance.absence_reason, "event_date": event.starts_at, "updated_at": attendance.updated_at})
    for progress, player, exercise in session.exec(
        select(ExerciseProgress, Player, Exercise)
        .join(ExerciseAssignment, ExerciseAssignment.id == ExerciseProgress.assignment_id)
        .join(Player, Player.id == ExerciseAssignment.player_id)
        .join(Exercise, Exercise.id == ExerciseAssignment.exercise_id)
        .order_by(ExerciseProgress.updated_at.desc())
        .limit(20)
    ):
        items.append({"kind": "progress", "player": player.name, "label": exercise.title, "value": progress.repetitions, "updated_at": progress.updated_at})
    for checkin, player, exercise in session.exec(
        select(ExerciseCheckin, Player, Exercise)
        .join(Player, Player.id == ExerciseCheckin.player_id)
        .join(Exercise, Exercise.id == ExerciseCheckin.exercise_id)
        .order_by(ExerciseCheckin.updated_at.desc()).limit(20)
    ):
        items.append({"kind": "checkin", "player": player.name, "label": exercise.title, "value": checkin.completed, "event_date": checkin.activity_date, "updated_at": checkin.updated_at})
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)[:20]


@router.get("/attendance-summary")
def attendance_summary(_: Principal = Depends(require_admin), session: Session = Depends(get_session)) -> list[dict]:
    rows = {player.id: {"player_id": player.id, "total": 0, "attending": 0} for player in session.exec(select(Player))}
    for attendance in session.exec(select(Attendance)):
        if attendance.player_id in rows:
            rows[attendance.player_id]["total"] += 1
            rows[attendance.player_id]["attending"] += int(attendance.attending)
    return [{**row, "percentage": round(row["attending"] * 100 / row["total"]) if row["total"] else None} for row in rows.values()]


@router.get("/event-attendance-summary")
def event_attendance_summary(_: Principal = Depends(require_admin), session: Session = Depends(get_session)) -> list[dict]:
    events = {event.id: event for event in session.exec(select(Event))}
    rows = {event_id: {"event_id": event_id, "total": 0, "attending": 0} for event_id in events}
    for attendance in session.exec(select(Attendance)):
        if attendance.event_id in rows:
            rows[attendance.event_id]["total"] += 1
            rows[attendance.event_id]["attending"] += int(attendance.attending)
    return [{**row, "title": events[row["event_id"]].title, "starts_at": events[row["event_id"]].starts_at} for row in rows.values() if row["total"]]
