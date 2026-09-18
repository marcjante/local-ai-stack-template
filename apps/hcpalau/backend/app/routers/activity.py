"""Recent player actions for the coaching dashboard."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from ..auth import Principal, require_admin
from ..database import get_session
from ..models import Attendance, Event, Exercise, ExerciseAssignment, ExerciseCheckin, ExerciseProgress, Player, Team, TeamPlayer


router = APIRouter(prefix="/activity", tags=["activity"])


def _team_player_ids(session: Session, principal: Principal, team: Optional[str]) -> Optional[set[int]]:
    if principal.team_id is not None:
        team_id = principal.team_id
    elif team:
        selected = session.exec(select(Team).where(Team.slug == team)).first()
        team_id = selected.id if selected else None
    else:
        return None
    return {row.player_id for row in session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team_id))}


@router.get("")
def recent_activity(
    principal: Principal = Depends(require_admin),
    team: Optional[str] = Query(default=None, max_length=64),
    session: Session = Depends(get_session),
) -> list[dict]:
    player_ids = _team_player_ids(session, principal, team)
    items: list[dict] = []
    for attendance, player, event in session.exec(
        select(Attendance, Player, Event)
        .join(Player, Player.id == Attendance.player_id)
        .join(Event, Event.id == Attendance.event_id)
        .order_by(Attendance.updated_at.desc())
        .limit(20)
    ):
        if player_ids is not None and player.id not in player_ids:
            continue
        items.append({"kind": "attendance", "player": player.name, "label": event.title, "value": attendance.attending, "reason": attendance.absence_reason, "event_date": event.starts_at, "updated_at": attendance.updated_at})
    for progress, player, exercise in session.exec(
        select(ExerciseProgress, Player, Exercise)
        .join(ExerciseAssignment, ExerciseAssignment.id == ExerciseProgress.assignment_id)
        .join(Player, Player.id == ExerciseAssignment.player_id)
        .join(Exercise, Exercise.id == ExerciseAssignment.exercise_id)
        .order_by(ExerciseProgress.updated_at.desc())
        .limit(20)
    ):
        if player_ids is not None and player.id not in player_ids:
            continue
        items.append({"kind": "progress", "player": player.name, "label": exercise.title, "value": progress.repetitions, "updated_at": progress.updated_at})
    for checkin, player, exercise in session.exec(
        select(ExerciseCheckin, Player, Exercise)
        .join(Player, Player.id == ExerciseCheckin.player_id)
        .join(Exercise, Exercise.id == ExerciseCheckin.exercise_id)
        .order_by(ExerciseCheckin.updated_at.desc()).limit(20)
    ):
        if player_ids is not None and player.id not in player_ids:
            continue
        items.append({"kind": "checkin", "player": player.name, "label": exercise.title, "value": checkin.completed, "event_date": checkin.activity_date, "updated_at": checkin.updated_at})
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)[:20]


@router.get("/attendance-summary")
def attendance_summary(principal: Principal = Depends(require_admin), team: Optional[str] = Query(default=None, max_length=64), session: Session = Depends(get_session)) -> list[dict]:
    player_ids = _team_player_ids(session, principal, team)
    rows = {player.id: {"player_id": player.id, "total": 0, "attending": 0} for player in session.exec(select(Player)) if player_ids is None or player.id in player_ids}
    for attendance in session.exec(select(Attendance)):
        if attendance.player_id in rows:
            rows[attendance.player_id]["total"] += 1
            rows[attendance.player_id]["attending"] += int(attendance.attending)
    return [{**row, "percentage": round(row["attending"] * 100 / row["total"]) if row["total"] else None} for row in rows.values()]


@router.get("/event-attendance-summary")
def event_attendance_summary(principal: Principal = Depends(require_admin), team: Optional[str] = Query(default=None, max_length=64), session: Session = Depends(get_session)) -> list[dict]:
    team_id = principal.team_id
    if team_id is None and team:
        selected = session.exec(select(Team).where(Team.slug == team)).first()
        team_id = selected.id if selected else None
    events = {event.id: event for event in session.exec(select(Event)) if team_id is None or event.team_id == team_id}
    rows = {event_id: {"event_id": event_id, "total": 0, "attending": 0} for event_id in events}
    for attendance in session.exec(select(Attendance)):
        if attendance.event_id in rows:
            rows[attendance.event_id]["total"] += 1
            rows[attendance.event_id]["attending"] += int(attendance.attending)
    return [{**row, "title": events[row["event_id"]].title, "starts_at": events[row["event_id"]].starts_at} for row in rows.values() if row["total"]]
