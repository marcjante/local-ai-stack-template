"""Private per-match MVP recognition selected by the coaching role."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_admin, require_player_access
from ..database import get_session
from ..models import Event, MvpRecognition, Player, utc_now
from ..schemas import MvpRead, MvpUpdate


router = APIRouter(prefix="/mvp", tags=["mvp"])


@router.put("/{event_id}/{player_id}", response_model=MvpRead)
def set_match_mvp(
    event_id: int,
    player_id: int,
    body: MvpUpdate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> MvpRecognition:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    if event.event_type != "match":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MVP recognition can only be assigned to matches",
        )
    if session.get(Player, player_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    recognition = session.exec(
        select(MvpRecognition).where(MvpRecognition.event_id == event_id)
    ).first()
    if recognition is None:
        recognition = MvpRecognition(event_id=event_id, player_id=player_id, note=body.note)
    else:
        recognition.player_id = player_id
        recognition.note = body.note
        recognition.awarded_at = utc_now()
    session.add(recognition)
    session.commit()
    session.refresh(recognition)
    return recognition


@router.get("/player/{player_id}", response_model=list[MvpRead])
def list_player_mvp_recognitions(
    player_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[MvpRecognition]:
    require_player_access(player_id, principal)
    statement = (
        select(MvpRecognition)
        .where(MvpRecognition.player_id == player_id)
        .order_by(MvpRecognition.awarded_at)
    )
    return list(session.exec(statement))


@router.get("/event/{event_id}", response_model=MvpRead)
def get_match_mvp(
    event_id: int,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> MvpRecognition:
    recognition = session.exec(
        select(MvpRecognition).where(MvpRecognition.event_id == event_id)
    ).first()
    if recognition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MVP not assigned")
    return recognition
