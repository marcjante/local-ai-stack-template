from sqlmodel import Session

from backend.app.database import engine
from backend.app.models import Team


def test_team_token_authenticates_and_only_global_admin_rotates(client, admin_headers) -> None:
    with Session(engine) as session:
        team = Team(slug="infantil-d", name="Infantil D", admin_token="team-admin-token")
        session.add(team)
        session.commit()
        session.refresh(team)
        team_id = team.id

    response = client.get("/teams", headers={"Authorization": "Bearer team-admin-token"})
    assert response.status_code == 200
    assert response.json() == [{"id": team_id, "slug": "infantil-d", "name": "Infantil D"}]

    forbidden = client.patch(
        f"/teams/{team_id}/admin-token",
        json={"admin_token": "replacement-team-token"},
        headers={"Authorization": "Bearer team-admin-token"},
    )
    assert forbidden.status_code == 403

    rotated = client.patch(
        f"/teams/{team_id}/admin-token",
        json={"admin_token": "replacement-team-token"},
        headers=admin_headers,
    )
    assert rotated.status_code == 200
    assert rotated.json()["admin_token"] == "replacement-team-token"
    assert client.get("/auth/session", headers={"Authorization": "Bearer replacement-team-token"}).json()["role"] == "admin"


def test_global_admin_can_create_team_with_generated_token(client, admin_headers) -> None:
    response = client.post("/teams", json={"slug": "juvenil-a", "name": "Juvenil A"}, headers=admin_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "juvenil-a"
    assert len(body["admin_token"]) >= 16
    assert client.get("/teams", headers={"Authorization": f"Bearer {body['admin_token']}"}).json()[0]["slug"] == "juvenil-a"
