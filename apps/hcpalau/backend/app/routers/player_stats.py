"""Additive, idempotent individual statistics for federation imports."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from ..auth import Principal, get_current_principal, require_admin, require_player_access
from ..database import get_session
from ..models import Player, PlayerStats, PlayerStatsImport, utc_now
from ..schemas import PlayerStatsIncrement, PlayerStatsRead


router = APIRouter(prefix="/player-stats", tags=["player-stats"])


@router.post("/{player_id}/increment", response_model=PlayerStatsRead)
def increment_player_stats(
    player_id: int,
    body: PlayerStatsIncrement,
    _: Principal = Depends(require_admin),
    session: Session = Depends(get_session),
) -> PlayerStats:
    if session.get(Player, player_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    stats = session.exec(
        select(PlayerStats).where(
            PlayerStats.player_id == player_id,
            PlayerStats.season == body.season,
        )
    ).first()
    existing_import = session.exec(
        select(PlayerStatsImport).where(
            PlayerStatsImport.player_id == player_id,
            PlayerStatsImport.season == body.season,
            PlayerStatsImport.source_key == body.source_key,
        )
    ).first()
    if existing_import is not None:
        if stats is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Import exists without matching statistics",
            )
        return stats

    if stats is None:
        stats = PlayerStats(player_id=player_id, season=body.season)
    for field in ("games", "goals", "assists", "yellow_cards", "red_cards"):
        setattr(stats, field, getattr(stats, field) + getattr(body, field))
    stats.updated_at = utc_now()
    session.add(stats)
    session.add(
        PlayerStatsImport(
            player_id=player_id,
            season=body.season,
            source_key=body.source_key,
        )
    )
    session.commit()
    session.refresh(stats)
    return stats


@router.get("/player/{player_id}", response_model=list[PlayerStatsRead])
def list_player_stats(
    player_id: int,
    season: str = Query(default="", max_length=32),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_session),
) -> list[PlayerStats]:
    require_player_access(player_id, principal)
    statement = select(PlayerStats).where(PlayerStats.player_id == player_id)
    if season:
        statement = statement.where(PlayerStats.season == season)
    statement = statement.order_by(PlayerStats.season)
    return list(session.exec(statement))
