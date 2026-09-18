"""Idempotently import the multi-team seed and attach legacy data to Infantil D.

The importer deliberately does not revoke or replace existing player tokens.
It accepts a seed shaped as ``{"teams": [...]}`` (or a top-level list) and
normalises common ``players``/``jugadors`` spellings used by exported data.
Run it after applying the multi-team Alembic migration.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
from pathlib import Path
from typing import Any

from sqlmodel import Session, SQLModel, select

from .app.config import get_settings
from .app.database import build_engine
from .app.models import Event, Player, Team, TeamPlayer


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "team"


def _teams(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("teams") or payload.get("equips") or []
    if not isinstance(payload, list):
        raise ValueError("Seed must contain a teams/equips list")
    return [row for row in payload if isinstance(row, dict)]


def _players(team: dict[str, Any]) -> list[Any]:
    rows = team.get("players") or team.get("jugadors") or []
    return rows if isinstance(rows, list) else []


def import_seed(session: Session, payload: Any) -> dict[str, int]:
    teams_created = players_created = memberships_created = 0
    imported_team_ids: list[int] = []
    for row in _teams(payload):
        name = str(row.get("name") or row.get("nom") or row.get("team") or "").strip()
        slug = _slug(str(row.get("slug") or row.get("id") or name))
        if not name:
            raise ValueError("Every team needs name/nom")
        team = session.exec(select(Team).where(Team.slug == slug)).first()
        if team is None:
            team = Team(slug=slug, name=name, admin_token=row.get("admin_token") or row.get("token_admin") or secrets.token_urlsafe(24))
            session.add(team)
            session.flush()
            teams_created += 1
        elif row.get("admin_token") or row.get("token_admin"):
            # Seed updates may add a token later, but never replace one that
            # is already active.
            team.admin_token = team.admin_token or row.get("admin_token") or row.get("token_admin")
        imported_team_ids.append(team.id)
        for raw_player in _players(row):
            if isinstance(raw_player, str):
                player_name, player_slug, token = raw_player, _slug(raw_player), None
            elif isinstance(raw_player, dict):
                player_name = str(raw_player.get("name") or raw_player.get("nom") or "").strip()
                player_slug = _slug(str(raw_player.get("slug") or raw_player.get("id") or player_name))
                token = raw_player.get("access_token") or raw_player.get("token")
            else:
                continue
            if not player_name:
                raise ValueError(f"Player without name in team {slug}")
            player = session.exec(select(Player).where(Player.slug == player_slug)).first()
            if player is None:
                player = Player(slug=player_slug, name=player_name, access_token=str(token or secrets.token_urlsafe(24)))
                session.add(player)
                session.flush()
                players_created += 1
            membership = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == team.id, TeamPlayer.player_id == player.id)).first()
            if membership is None:
                session.add(TeamPlayer(team_id=team.id, player_id=player.id))
                memberships_created += 1

    legacy = session.exec(select(Team).where(Team.slug == "infantil-d")).first()
    if legacy is not None:
        existing_players = session.exec(select(Player)).all()
        for player in existing_players:
            membership = session.exec(select(TeamPlayer).where(TeamPlayer.team_id == legacy.id, TeamPlayer.player_id == player.id)).first()
            if membership is None:
                session.add(TeamPlayer(team_id=legacy.id, player_id=player.id))
                memberships_created += 1
        for event in session.exec(select(Event).where(Event.team_id.is_(None))).all():
            event.team_id = legacy.id
            session.add(event)
    session.commit()
    return {"teams_created": teams_created, "players_created": players_created, "memberships_created": memberships_created, "teams_seen": len(imported_team_ids)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import HC Palau multi-team seed")
    parser.add_argument("seed", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.seed.read_text(encoding="utf-8"))
    settings = get_settings()
    engine = build_engine(settings.database_url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        print(import_seed(session, payload))


if __name__ == "__main__":
    main()
