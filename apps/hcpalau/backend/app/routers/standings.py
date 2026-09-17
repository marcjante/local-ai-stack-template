"""Competition standings, ready for a future isolated FECAPA synchronizer."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_admin
from ..database import get_session
from ..models import Standing, utc_now
from ..schemas import StandingRead, StandingUpdate


router = APIRouter(prefix="/standings", tags=["standings"])


@router.post("", response_model=StandingRead)
def upsert_standing(
    body: StandingUpdate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Standing:
    standing = session.exec(
        select(Standing).where(
            Standing.season == body.season,
            Standing.team == body.team,
        )
    ).first()
    if standing is None:
        standing = Standing.model_validate(body)
    else:
        for field, value in body.model_dump().items():
            setattr(standing, field, value)
        standing.updated_at = utc_now()

    session.add(standing)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another team already occupies this position",
        ) from None
    session.refresh(standing)
    return standing


@router.get("", response_model=list[StandingRead])
def list_standings(
    season: str = Query(min_length=1, max_length=32),
    _: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[Standing]:
    statement = (
        select(Standing)
        .where(Standing.season == season)
        .order_by(Standing.position)
    )
    return list(session.exec(statement))
