"""Team catalogue used by the global administrator's team selector."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_admin
from ..database import get_session
from ..models import Player, Team, TeamPlayer
from ..schemas import PlayerRead, TeamAdminRead, TeamAdminTokenUpdate, TeamCreate, TeamPlayerRead, TeamRead, TeamUpdate


router = APIRouter(prefix="/teams", tags=["teams"])


@router.patch("/{team_id}", response_model=TeamRead)
def update_team(
    team_id: int,
    body: TeamUpdate,
    principal: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Team:
    if principal.team_id is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the global administrator can edit teams")
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if body.name is not None:
        team.name = body.name.strip()
    if body.slug is not None:
        team.slug = body.slug
    session.add(team)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team slug already exists") from None
    session.refresh(team)
    return team


@router.post("", response_model=TeamAdminRead, status_code=status.HTTP_201_CREATED)
def create_team(
    body: TeamCreate,
    principal: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Team:
    if principal.team_id is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the global administrator can create teams")
    team = Team(slug=body.slug, name=body.name, admin_token=body.admin_token or secrets.token_urlsafe(24))
    session.add(team)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team slug or token already exists") from None
    session.refresh(team)
    return team


@router.get("", response_model=list[TeamRead])
def list_teams(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[Team]:
    if principal.team_id is not None:
        team = session.get(Team, principal.team_id)
        return [team] if team is not None else []
    if principal.role == "player":
        statement = select(Team).join(TeamPlayer, TeamPlayer.team_id == Team.id).where(TeamPlayer.player_id == principal.player_id).order_by(Team.name)
        return list(session.exec(statement))
    return list(session.exec(select(Team).order_by(Team.name)))


@router.patch("/{team_id}/admin-token", response_model=TeamAdminRead)
def update_team_admin_token(
    team_id: int,
    body: TeamAdminTokenUpdate,
    principal: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Team:
    if principal.team_id is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the global administrator can rotate team tokens")
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    team.admin_token = body.admin_token
    session.add(team)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team token already exists") from None
    session.refresh(team)
    return team


@router.put("/{team_id}/players/{player_id}", response_model=TeamPlayerRead)
def add_team_player(
    team_id: int,
    player_id: int,
    principal: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> TeamPlayer:
    if principal.team_id is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the global administrator can manage memberships")
    if session.get(Team, team_id) is None or session.get(Player, player_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team or player not found")
    membership = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team_id, TeamPlayer.player_id == player_id)).first()
    if membership is None:
        membership = TeamPlayer(team_id=team_id, player_id=player_id)
        session.add(membership)
        session.commit()
        session.refresh(membership)
    return membership


@router.get("/{team_id}/players", response_model=list[PlayerRead])
def list_team_players(
    team_id: int,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[Player]:
    if session.get(Team, team_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if principal.team_id is not None and principal.team_id != team_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Team access required")
    if principal.role == "player":
        own_membership = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team_id, TeamPlayer.player_id == principal.player_id)).first()
        if own_membership is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Team access required")
    statement = select(Player).join(TeamPlayer, TeamPlayer.player_id == Player.id).where(TeamPlayer.team_id == team_id).order_by(Player.name)
    return list(session.exec(statement))


@router.delete("/{team_id}/players/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_team_player(
    team_id: int,
    player_id: int,
    principal: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> None:
    if principal.team_id is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the global administrator can manage memberships")
    membership = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team_id, TeamPlayer.player_id == player_id)).first()
    if membership is not None:
        session.delete(membership)
        session.commit()
