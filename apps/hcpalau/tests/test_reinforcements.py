from datetime import datetime, timedelta, timezone


def create_player(client, admin_headers):
    response = client.post(
        "/players",
        json={"slug": "biel", "name": "Biel", "access_token": "biel-player-token"},
        headers=admin_headers,
    )
    assert response.status_code == 201


def create_event(client, admin_headers, event_type="match"):
    response = client.post(
        "/events",
        json={
            "title": "Partit de lliga",
            "starts_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "event_type": event_type,
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def reinforcement_payload(event_id):
    return {
        "event_id": event_id,
        "player_name": "Jugador reforç",
        "source_team": "Infantil C",
        "playing_position": "field",
    }


def test_admin_manages_match_reinforcement(client, admin_headers) -> None:
    event = create_event(client, admin_headers)
    created = client.post(
        "/reinforcements",
        json=reinforcement_payload(event["id"]),
        headers=admin_headers,
    )
    confirmed = client.patch(
        f"/reinforcements/{created.json()['id']}",
        json={"confirmed": True},
        headers=admin_headers,
    )
    listed = client.get(f"/reinforcements/event/{event['id']}", headers=admin_headers)

    assert created.status_code == 201
    assert confirmed.status_code == 200
    assert confirmed.json()["confirmed"] is True
    assert listed.json() == [confirmed.json()]


def test_players_cannot_access_reinforcement_data(client, admin_headers) -> None:
    create_player(client, admin_headers)
    event = create_event(client, admin_headers)
    created = client.post(
        "/reinforcements",
        json=reinforcement_payload(event["id"]),
        headers=admin_headers,
    ).json()
    headers = {"Authorization": "Bearer biel-player-token"}

    assert client.get(f"/reinforcements/event/{event['id']}", headers=headers).status_code == 403
    assert client.patch(
        f"/reinforcements/{created['id']}",
        json={"confirmed": True},
        headers=headers,
    ).status_code == 403
    assert client.delete(f"/reinforcements/{created['id']}", headers=headers).status_code == 403


def test_training_rejects_reinforcement(client, admin_headers) -> None:
    event = create_event(client, admin_headers, event_type="training")

    response = client.post(
        "/reinforcements",
        json=reinforcement_payload(event["id"]),
        headers=admin_headers,
    )

    assert response.status_code == 400


def test_duplicate_reinforcement_is_rejected(client, admin_headers) -> None:
    event = create_event(client, admin_headers)
    payload = reinforcement_payload(event["id"])
    assert client.post("/reinforcements", json=payload, headers=admin_headers).status_code == 201

    response = client.post("/reinforcements", json=payload, headers=admin_headers)

    assert response.status_code == 409
