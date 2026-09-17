"""Authenticated session bootstrap for the browser client."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from ..auth import Principal, get_current_principal
from ..database import get_session
from ..models import Player
from ..schemas import SessionRead


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/session", response_model=SessionRead)
def get_session_identity(
    jugador: Optional[str] = Query(default=None, max_length=64),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> SessionRead:
    if principal.role == "admin":
        return SessionRead(role="admin")

    player = session.get(Player, principal.player_id)
    if player is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if jugador is not None and jugador != player.slug:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token does not belong to the requested player",
        )
    return SessionRead(role="player", player=player)
