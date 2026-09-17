"""Private exam periods used to adapt an individual player's workload."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_admin, require_player_access
from ..database import get_session
from ..models import ExamPeriod, Player
from ..schemas import ExamPeriodCreate, ExamPeriodRead


router = APIRouter(prefix="/exam-periods", tags=["exam-periods"])


@router.post("", response_model=ExamPeriodRead, status_code=status.HTTP_201_CREATED)
def create_exam_period(
    body: ExamPeriodCreate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> ExamPeriod:
    if body.end_date < body.start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End date cannot be before start date",
        )
    if session.get(Player, body.player_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    period = ExamPeriod.model_validate(body)
    session.add(period)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Exam period already exists",
        ) from None
    session.refresh(period)
    return period


@router.get("/player/{player_id}", response_model=list[ExamPeriodRead])
def list_player_exam_periods(
    player_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[ExamPeriod]:
    require_player_access(player_id, principal)
    statement = (
        select(ExamPeriod)
        .where(ExamPeriod.player_id == player_id)
        .order_by(ExamPeriod.start_date)
    )
    return list(session.exec(statement))


@router.delete("/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_exam_period(
    period_id: int,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Response:
    period = session.get(ExamPeriod, period_id)
    if period is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam period not found")
    session.delete(period)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
