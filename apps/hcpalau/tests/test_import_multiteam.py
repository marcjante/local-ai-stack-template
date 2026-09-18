from datetime import datetime

from sqlmodel import Session, SQLModel, select

from backend.app.database import build_engine
from backend.app.models import Event, Player, Team, TeamPlayer
from backend.import_multiteam import import_seed


def test_import_multiteam_is_idempotent_and_attaches_legacy_data(tmp_path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'import.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Player(slug="biel", name="Biel", access_token="legacy-player-token"))
        session.add(Event(title="Històric", starts_at=datetime(2026, 1, 1, 18), event_type="training"))
        session.commit()
        seed = {
            "teams": [{
                "slug": "infantil-d",
                "name": "Infantil D",
                "admin_token": "infantil-admin-token",
                "players": [{"slug": "nou", "name": "Nou", "access_token": "new-player-token"}],
            }]
        }

        first = import_seed(session, seed)
        second = import_seed(session, seed)

        assert first == {"teams_created": 1, "players_created": 1, "memberships_created": 2, "teams_seen": 1}
        assert second == {"teams_created": 0, "players_created": 0, "memberships_created": 0, "teams_seen": 1}
        team = session.exec(select(Team).where(Team.slug == "infantil-d")).one()
        assert team.admin_token == "infantil-admin-token"
        assert session.exec(select(Player).where(Player.slug == "biel")).one().access_token == "legacy-player-token"
        assert len(session.exec(select(TeamPlayer)).all()) == 2
        assert session.exec(select(Event)).one().team_id == team.id
