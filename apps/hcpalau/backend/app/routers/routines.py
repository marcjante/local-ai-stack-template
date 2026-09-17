"""Ordered exercise routines assigned to one player at a time."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_admin, require_player_access
from ..database import get_session
from ..models import Exercise, Player, Routine, RoutineExercise
from ..schemas import (
    RoutineCreate,
    RoutineExerciseCreate,
    RoutineExerciseRead,
    RoutineRead,
)


router = APIRouter(prefix="/routines", tags=["routines"])


@router.post("", response_model=RoutineRead, status_code=status.HTTP_201_CREATED)
def create_routine(
    body: RoutineCreate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Routine:
    if session.get(Player, body.player_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    routine = Routine.model_validate(body)
    session.add(routine)
    session.commit()
    session.refresh(routine)
    return routine


@router.post(
    "/{routine_id}/exercises",
    response_model=RoutineExerciseRead,
    status_code=status.HTTP_201_CREATED,
)
def add_routine_exercise(
    routine_id: int,
    body: RoutineExerciseCreate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> RoutineExercise:
    if session.get(Routine, routine_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")
    if session.get(Exercise, body.exercise_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercise not found")
    item = RoutineExercise(routine_id=routine_id, **body.model_dump())
    session.add(item)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Exercise or position already exists in this routine",
        ) from None
    session.refresh(item)
    return item


@router.get("/player/{player_id}", response_model=list[RoutineRead])
def list_player_routines(
    player_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[Routine]:
    require_player_access(player_id, principal)
    statement = select(Routine).where(Routine.player_id == player_id).order_by(Routine.created_at)
    return list(session.exec(statement))


@router.get("/{routine_id}/exercises", response_model=list[RoutineExerciseRead])
def list_routine_exercises(
    routine_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[RoutineExercise]:
    routine = session.get(Routine, routine_id)
    if routine is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")
    require_player_access(routine.player_id, principal)
    statement = (
        select(RoutineExercise)
        .where(RoutineExercise.routine_id == routine_id)
        .order_by(RoutineExercise.position)
    )
    return list(session.exec(statement))
