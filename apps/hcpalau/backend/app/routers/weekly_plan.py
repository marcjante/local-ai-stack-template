"""Weekly exercise lists selected by the coach."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_admin, require_player_access
from ..database import get_session
from ..models import Exercise, Player, WeeklyExercise
from ..schemas import WeeklyExerciseCreate, WeeklyExerciseRead

router = APIRouter(prefix="/weekly-plan", tags=["weekly-plan"])


@router.post("", response_model=WeeklyExerciseRead, status_code=status.HTTP_201_CREATED)
def add_weekly_exercise(body: WeeklyExerciseCreate, _: Principal = Depends(require_admin), session: Session = Depends(get_session)) -> WeeklyExercise:
    if session.get(Player, body.player_id) is None or session.get(Exercise, body.exercise_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player or exercise not found")
    row = WeeklyExercise.model_validate(body)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Exercise already in this weekly plan") from None
    session.refresh(row)
    return row


@router.get("/player/{player_id}", response_model=list[WeeklyExerciseRead])
def list_weekly_plan(player_id: int, week_start: Optional[date] = None, principal: Principal = Depends(get_current_principal), session: Session = Depends(get_session)) -> list[WeeklyExercise]:
    require_player_access(player_id, principal)
    statement = select(WeeklyExercise).where(WeeklyExercise.player_id == player_id)
    if week_start:
        statement = statement.where(WeeklyExercise.week_start == week_start)
    return list(session.exec(statement.order_by(WeeklyExercise.week_start, WeeklyExercise.id)))
