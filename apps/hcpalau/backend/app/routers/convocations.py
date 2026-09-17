"""Per-player match convocations managed by the coaching role."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_admin, require_player_access
from ..database import get_session
from ..models import Convocation, Event, Player, utc_now
from ..schemas import ConvocationRead, ConvocationUpdate, TeamConvocationRead


router = APIRouter(prefix="/convocations", tags=["convocations"])


@router.put("/{event_id}/{player_id}", response_model=ConvocationRead)
def set_convocation(
    event_id: int,
    player_id: int,
    body: ConvocationUpdate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Convocation:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    if event.event_type != "match":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Convocations can only be set for matches",
        )
    if session.get(Player, player_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    convocation = session.exec(
        select(Convocation).where(
            Convocation.event_id == event_id,
            Convocation.player_id == player_id,
        )
    ).first()
    if convocation is None:
        convocation = Convocation(event_id=event_id, player_id=player_id, **body.model_dump())
    else:
        convocation.selection_status = body.selection_status
        convocation.note = body.note
        convocation.updated_at = utc_now()
    session.add(convocation)
    session.commit()
    session.refresh(convocation)
    return convocation


@router.get("/player/{player_id}", response_model=list[ConvocationRead])
def list_player_convocations(
    player_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[Convocation]:
    require_player_access(player_id, principal)
    statement = (
        select(Convocation)
        .where(Convocation.player_id == player_id)
        .order_by(Convocation.event_id)
    )
    return list(session.exec(statement))


@router.get("/event/{event_id}", response_model=list[ConvocationRead])
def list_event_convocations(
    event_id: int,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> list[Convocation]:
    if session.get(Event, event_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    statement = (
        select(Convocation)
        .where(Convocation.event_id == event_id)
        .order_by(Convocation.player_id)
    )
    return list(session.exec(statement))


@router.get("/event/{event_id}/team", response_model=list[TeamConvocationRead])
def list_selected_team(
    event_id: int,
    _: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[TeamConvocationRead]:
    if session.get(Event, event_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    rows = session.exec(
        select(Convocation, Player)
        .join(Player, Player.id == Convocation.player_id)
        .where(Convocation.event_id == event_id, Convocation.selection_status == "selected")
        .order_by(Player.name)
    )
    return [TeamConvocationRead(player_id=convocation.player_id, player_name=player.name) for convocation, player in rows]
