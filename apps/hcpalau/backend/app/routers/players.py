"""Player administration and self-service endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_admin, require_player_access
from ..database import get_session
from ..models import Player
from ..schemas import PlayerAccessUpdate, PlayerAdminRead, PlayerCreate, PlayerRead


router = APIRouter(prefix="/players", tags=["players"])


@router.post("", response_model=PlayerAdminRead, status_code=status.HTTP_201_CREATED)
def create_player(
    body: PlayerCreate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Player:
    player = Player.model_validate(body)
    session.add(player)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Player slug or access token already exists",
        ) from None
    session.refresh(player)
    return player


@router.get("", response_model=list[PlayerAdminRead])
def list_players(
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> list[Player]:
    return list(session.exec(select(Player).order_by(Player.name)))


@router.get("/{player_id}", response_model=PlayerRead)
def get_player(
    player_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> Player:
    require_player_access(player_id, principal)
    player = session.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    return player


@router.patch("/{player_id}/access", response_model=PlayerAdminRead)
def update_player_access(
    player_id: int,
    body: PlayerAccessUpdate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Player:
    player = session.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    player.access_active = body.access_active
    session.add(player)
    session.commit()
    session.refresh(player)
    return player
