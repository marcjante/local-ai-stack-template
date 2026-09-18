from sqlmodel import Session, select

from backend.app.database import engine
from backend.app.models import Player, Team, TeamPlayer


def test_global_admin_can_manage_team_memberships_idempotently(client, admin_headers) -> None:
    player = client.post(
        "/players",
        json={"slug": "biel", "name": "Biel", "access_token": "biel-membership-token"},
        headers=admin_headers,
    ).json()
    with Session(engine) as session:
        team = Team(slug="infantil-d", name="Infantil D")
        session.add(team)
        session.commit()
        session.refresh(team)
        team_id = team.id

    first = client.put(f"/teams/{team_id}/players/{player['id']}", headers=admin_headers)
    second = client.put(f"/teams/{team_id}/players/{player['id']}", headers=admin_headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["player_id"] == player["id"]

    with Session(engine) as session:
        assert len(session.exec(select(TeamPlayer)).all()) == 1

    removed = client.delete(f"/teams/{team_id}/players/{player['id']}", headers=admin_headers)
    assert removed.status_code == 204


def test_player_sees_only_assigned_teams(client, admin_headers) -> None:
    player = client.post(
        "/players",
        json={"slug": "biel", "name": "Biel", "access_token": "biel-team-list-token"},
        headers=admin_headers,
    ).json()
    with Session(engine) as session:
        own = Team(slug="infantil-d", name="Infantil D")
        other = Team(slug="juvenil-a", name="Juvenil A")
        session.add(own)
        session.add(other)
        session.commit()
        session.refresh(own)
        session.add(TeamPlayer(team_id=own.id, player_id=player["id"]))
        session.commit()

    response = client.get("/teams", headers={"Authorization": "Bearer biel-team-list-token"})
    assert response.status_code == 200
    assert [row["slug"] for row in response.json()] == ["infantil-d"]
