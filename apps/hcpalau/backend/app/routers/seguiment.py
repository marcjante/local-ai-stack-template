"""Individual player follow-up notes with explicit player visibility."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_admin, require_player_access
from ..database import get_session
from ..models import FollowUp, Player
from ..schemas import FollowUpCreate, FollowUpRead


router = APIRouter(prefix="/seguiment", tags=["seguiment"])


@router.post("", response_model=FollowUpRead, status_code=status.HTTP_201_CREATED)
def create_follow_up(
    body: FollowUpCreate,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> FollowUp:
    if session.get(Player, body.player_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    follow_up = FollowUp.model_validate(body)
    session.add(follow_up)
    session.commit()
    session.refresh(follow_up)
    return follow_up


@router.get("/player/{player_id}", response_model=list[FollowUpRead])
def list_player_follow_up(
    player_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[FollowUp]:
    require_player_access(player_id, principal)
    statement = select(FollowUp).where(FollowUp.player_id == player_id)
    if principal.role == "player":
        statement = statement.where(FollowUp.visible_to_player.is_(True))
    statement = statement.order_by(FollowUp.observed_on, FollowUp.id)
    return list(session.exec(statement))


@router.delete("/{follow_up_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_follow_up(
    follow_up_id: int,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> None:
    follow_up = session.get(FollowUp, follow_up_id)
    if follow_up is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Follow-up not found")
    session.delete(follow_up)
    session.commit()
