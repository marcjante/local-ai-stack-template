from datetime import datetime, timedelta, timezone


def create_player(client, admin_headers, slug, token):
    response = client.post(
        "/players",
        json={"slug": slug, "name": slug.title(), "access_token": token},
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def create_event(client, admin_headers, event_type="match"):
    response = client.post(
        "/events",
        json={
            "title": "Partit de lliga",
            "starts_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "event_type": event_type,
            "location": "Pavelló Maria Víctor",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def test_admin_sets_and_updates_individual_convocation(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    event = create_event(client, admin_headers)

    selected = client.put(
        f"/convocations/{event['id']}/{player['id']}",
        json={"selection_status": "selected", "note": "Arribar 45 minuts abans"},
        headers=admin_headers,
    )
    reserve = client.put(
        f"/convocations/{event['id']}/{player['id']}",
        json={"selection_status": "reserve"},
        headers=admin_headers,
    )

    assert selected.status_code == 200
    assert reserve.status_code == 200
    assert reserve.json()["id"] == selected.json()["id"]
    assert reserve.json()["selection_status"] == "reserve"


def test_player_only_reads_own_convocations(client, admin_headers) -> None:
    biel = create_player(client, admin_headers, "biel", "biel-player-token")
    pau = create_player(client, admin_headers, "pau", "pau-player-token-")
    event = create_event(client, admin_headers)
    client.put(
        f"/convocations/{event['id']}/{pau['id']}",
        json={"selection_status": "selected"},
        headers=admin_headers,
    )
    headers = {"Authorization": "Bearer biel-player-token"}

    own = client.get(f"/convocations/player/{biel['id']}", headers=headers)
    other = client.get(f"/convocations/player/{pau['id']}", headers=headers)
    event_list = client.get(f"/convocations/event/{event['id']}", headers=headers)

    assert own.status_code == 200
    assert own.json() == []
    assert other.status_code == 403
    assert event_list.status_code == 403


def test_player_cannot_set_convocation(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    event = create_event(client, admin_headers)

    response = client.put(
        f"/convocations/{event['id']}/{player['id']}",
        json={"selection_status": "selected"},
        headers={"Authorization": "Bearer biel-player-token"},
    )

    assert response.status_code == 403


def test_training_cannot_have_convocation(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    event = create_event(client, admin_headers, event_type="training")

    response = client.put(
        f"/convocations/{event['id']}/{player['id']}",
        json={"selection_status": "selected"},
        headers=admin_headers,
    )

    assert response.status_code == 400
