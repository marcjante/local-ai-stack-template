"""Idempotently import the multi-team seed and attach legacy data to Infantil D.

The importer deliberately does not revoke or replace existing player tokens.
It accepts a seed shaped as ``{"teams": [...]}`` (or a top-level list) and
normalises common ``players``/``jugadors`` spellings used by exported data.
Run it after applying the multi-team Alembic migration.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import secrets
from pathlib import Path
from typing import Any

from sqlmodel import Session, SQLModel, select

from .app.config import get_settings
from .app.database import build_engine
from .app.models import Event, Player, Team, TeamPlayer


# The first PDF-derived seed used longer competition labels.  Keep those
# slugs as aliases so importing the authoritative CSV never creates duplicate
# teams or breaks links already distributed to coaches and players.
LEGACY_TEAM_SLUGS = {
    "prebe-iniciacio": "prebenjami-d-plata",
    "prebe-b": "prebenjami-b-plata",
    "prebe-a": "prebenjami-a-or",
    "benjami-d": "benjami-d-plata",
    "benjami-c": "benjami-c-or",
    "benjami-b": "benjami-b-or",
    "benjami-a": "benjami-a-or",
    "alevi-d": "alevi-d-plata",
    "alevi-c": "alevi-c-or",
    "alevi-b": "alevi-b-or",
    "alevi-a": "alevi-a-s55c",
    "infantil-e": "infantil-e-plata",
    "infantil-c": "infantil-c-or",
    "infantil-b": "infantil-b-or",
    "infantil-a": "infantil-a-ssp",
    "juvenil-c": "juvenil-c-plata",
    "juvenil-b": "juvenil-b-ssp",
    "juvenil-a": "juvenil-a-ssp",
    "junior": "junior-ssp",
    "fem11-b": "fem-11-b-plata",
    "fem11-a": "fem-11-a-or",
    "fem13-b": "fem-13-b-or",
    "fem13-a": "fem-13-a-or",
    "fem15-b": "fem-15-b-or",
    "fem15-a": "fem-15-a-or",
    "fem17-b": "fem-17-b-pss",
    "fem17-a": "fem-17-a-sss",
    "fem19-b": "fem-19-b-pss",
    "fem19-a": "fem-19-a-pss",
}


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


def csv_seed(path: Path) -> dict[str, Any]:
    """Convert the club roster CSV into the importer's normalised payload."""
    grouped: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            raw_slug = str(row.get("equip_id") or row.get("equip") or "").strip()
            player_name = str(row.get("jugador") or "").strip()
            if not raw_slug or not player_name:
                continue
            team = grouped.setdefault(raw_slug, {
                "slug": raw_slug,
                "name": str(row.get("equip") or raw_slug).strip(),
                "players": [],
            })
            player = {"name": player_name}
            role = str(row.get("rol") or "").strip()
            if role:
                player["role"] = role
            note = str(row.get("nota") or "").strip()
            if note:
                player["note"] = note
            team["players"].append(player)
    return {"season": "2026-27", "teams": list(grouped.values())}


def import_seed(session: Session, payload: Any, *, attach_legacy: bool = True) -> dict[str, int]:
    teams_created = players_created = memberships_created = 0
    imported_team_ids: list[int] = []
    for row in _teams(payload):
        name = str(row.get("name") or row.get("nom") or row.get("team") or "").strip()
        slug = _slug(str(row.get("slug") or row.get("id") or name))
        if not name:
            raise ValueError("Every team needs name/nom")
        team = session.exec(select(Team).where(Team.slug == slug)).first()
        if team is None:
            legacy_slug = LEGACY_TEAM_SLUGS.get(slug)
            if legacy_slug:
                team = session.exec(select(Team).where(Team.slug == legacy_slug)).first()
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

    legacy = session.exec(select(Team).where(Team.slug == "infantil-d")).first() if attach_legacy else None
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
    is_csv = args.seed.suffix.lower() == ".csv"
    if is_csv:
        payload = csv_seed(args.seed)
    else:
        payload = json.loads(args.seed.read_text(encoding="utf-8"))
    settings = get_settings()
    engine = build_engine(settings.database_url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        print(import_seed(session, payload, attach_legacy=not is_csv))


if __name__ == "__main__":
    main()
