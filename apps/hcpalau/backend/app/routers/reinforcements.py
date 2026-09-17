"""Administrative management of external players reinforcing a match."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..auth import Principal, require_admin
from ..database import get_session
from ..models import Event, Reinforcement
from ..schemas import (
    ReinforcementConfirmationUpdate,
    ReinforcementCreate,
    ReinforcementRead,
)


router = APIRouter(prefix="/reinforcements", tags=["reinforcements"])


@router.post("", response_model=ReinforcementRead, status_code=status.HTTP_201_CREATED)
def create_reinforcement(
    body: ReinforcementCreate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Reinforcement:
    event = session.get(Event, body.event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    if event.event_type != "match":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reinforcements can only be added to matches",
        )
    reinforcement = Reinforcement.model_validate(body)
    session.add(reinforcement)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reinforcement already added to this match",
        ) from None
    session.refresh(reinforcement)
    return reinforcement


@router.get("/event/{event_id}", response_model=list[ReinforcementRead])
def list_event_reinforcements(
    event_id: int,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> list[Reinforcement]:
    if session.get(Event, event_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    statement = (
        select(Reinforcement)
        .where(Reinforcement.event_id == event_id)
        .order_by(Reinforcement.player_name)
    )
    return list(session.exec(statement))


@router.patch("/{reinforcement_id}", response_model=ReinforcementRead)
def update_reinforcement_confirmation(
    reinforcement_id: int,
    body: ReinforcementConfirmationUpdate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Reinforcement:
    reinforcement = session.get(Reinforcement, reinforcement_id)
    if reinforcement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reinforcement not found")
    reinforcement.confirmed = body.confirmed
    session.add(reinforcement)
    session.commit()
    session.refresh(reinforcement)
    return reinforcement


@router.delete("/{reinforcement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reinforcement(
    reinforcement_id: int,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Response:
    reinforcement = session.get(Reinforcement, reinforcement_id)
    if reinforcement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reinforcement not found")
    session.delete(reinforcement)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
