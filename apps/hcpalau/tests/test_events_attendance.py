from datetime import datetime, timedelta, timezone


def create_player(client, admin_headers, slug, token):
    response = client.post(
        "/players",
        json={"slug": slug, "name": slug.title(), "access_token": token},
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def create_event(client, admin_headers):
    response = client.post(
        "/events",
        json={
            "title": "Entrenament",
            "starts_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "event_type": "training",
            "location": "Pavelló Maria Víctor",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def test_active_player_can_list_events(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    event = create_event(client, admin_headers)
    headers = {"Authorization": "Bearer biel-player-token"}

    response = client.get("/events", headers=headers)

    assert response.status_code == 200
    assert response.json() == [event]
    assert player["access_active"] is True


def test_player_can_set_and_update_own_attendance(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    event = create_event(client, admin_headers)
    headers = {"Authorization": "Bearer biel-player-token"}

    first = client.patch(
        f"/attendance/{event['id']}/{player['id']}",
        json={"attending": True},
        headers=headers,
    )
    second = client.patch(
        f"/attendance/{event['id']}/{player['id']}",
        json={"attending": False, "absence_reason": "Examen de matemàtiques"},
        headers=headers,
    )
    listed = client.get(f"/attendance/{player['id']}", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert listed.json() == [second.json()]
    assert second.json()["absence_reason"] == "Examen de matemàtiques"


def test_player_must_explain_absence(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    event = create_event(client, admin_headers)
    response = client.patch(
        f"/attendance/{event['id']}/{player['id']}",
        json={"attending": False},
        headers={"Authorization": "Bearer biel-player-token"},
    )
    assert response.status_code == 422


def test_player_cannot_write_another_players_attendance(client, admin_headers) -> None:
    biel = create_player(client, admin_headers, "biel", "biel-player-token")
    pau = create_player(client, admin_headers, "pau", "pau-player-token-")
    event = create_event(client, admin_headers)
    headers = {"Authorization": "Bearer biel-player-token"}

    response = client.patch(
        f"/attendance/{event['id']}/{pau['id']}",
        json={"attending": True},
        headers=headers,
    )

    assert biel["id"] != pau["id"]
    assert response.status_code == 403


def test_revoked_player_cannot_read_events_or_attendance(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    event = create_event(client, admin_headers)
    headers = {"Authorization": "Bearer biel-player-token"}
    client.patch(
        f"/players/{player['id']}/access",
        json={"access_active": False},
        headers=admin_headers,
    )

    assert client.get("/events", headers=headers).status_code == 403
    assert client.get(f"/attendance/{player['id']}", headers=headers).status_code == 403
    assert client.patch(
        f"/attendance/{event['id']}/{player['id']}",
        json={"attending": True},
        headers=headers,
    ).status_code == 403
