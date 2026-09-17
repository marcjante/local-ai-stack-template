"""Bearer-token authentication for administrators and individual players."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Literal, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from .config import get_settings
from .database import get_session
from .models import Player


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    role: Literal["admin", "player"]
    player_id: Optional[int] = None


def get_current_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
        )

    token = credentials.credentials
    if secrets.compare_digest(token, get_settings().admin_token):
        return Principal(role="admin")

    player = session.exec(select(Player).where(Player.access_token == token)).first()
    if player is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if not player.access_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access disabled")
    return Principal(role="player", player_id=player.id)


def require_admin(principal: Principal = Depends(get_current_principal)) -> Principal:
    if principal.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return principal


def require_player_access(player_id: int, principal: Principal) -> None:
    if principal.role != "admin" and principal.player_id != player_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Players can only access their own data",
        )
