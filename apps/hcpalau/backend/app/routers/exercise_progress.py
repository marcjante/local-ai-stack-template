"""Weekly progress for an individually assigned exercise."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_player_access
from ..database import get_session
from ..models import ExerciseAssignment, ExerciseProgress, utc_now
from ..schemas import ExerciseProgressRead


router = APIRouter(prefix="/exercise-progress", tags=["exercise-progress"])


@router.post("/{assignment_id}/increment", response_model=ExerciseProgressRead)
def increment_progress(
    assignment_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> ExerciseProgress:
    assignment = session.get(ExerciseAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    require_player_access(assignment.player_id, principal)

    iso_year, iso_week, _ = datetime.now(timezone.utc).isocalendar()
    statement = select(ExerciseProgress).where(
        ExerciseProgress.assignment_id == assignment_id,
        ExerciseProgress.iso_year == iso_year,
        ExerciseProgress.iso_week == iso_week,
    )
    progress = session.exec(statement).first()
    if progress is None:
        progress = ExerciseProgress(
            assignment_id=assignment_id,
            iso_year=iso_year,
            iso_week=iso_week,
            repetitions=0,
        )
    if progress.repetitions >= 3:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Weekly exercise limit reached",
        )
    progress.repetitions += 1
    progress.updated_at = utc_now()
    session.add(progress)
    session.commit()
    session.refresh(progress)
    return progress


@router.get("/player/{player_id}", response_model=list[ExerciseProgressRead])
def list_progress(
    player_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[ExerciseProgress]:
    require_player_access(player_id, principal)
    statement = (
        select(ExerciseProgress)
        .join(ExerciseAssignment)
        .where(ExerciseAssignment.player_id == player_id)
        .order_by(ExerciseProgress.iso_year, ExerciseProgress.iso_week)
    )
    return list(session.exec(statement))
