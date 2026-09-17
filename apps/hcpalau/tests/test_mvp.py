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
            "starts_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "event_type": event_type,
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def test_admin_assigns_one_mvp_per_match(client, admin_headers) -> None:
    biel = create_player(client, admin_headers, "biel", "biel-player-token")
    pau = create_player(client, admin_headers, "pau", "pau-player-token-")
    event = create_event(client, admin_headers)

    first = client.put(
        f"/mvp/{event['id']}/{biel['id']}",
        json={"note": "Gran partit"},
        headers=admin_headers,
    )
    corrected = client.put(
        f"/mvp/{event['id']}/{pau['id']}",
        json={"note": "Correcció de l'entrenador"},
        headers=admin_headers,
    )

    assert first.status_code == 200
    assert corrected.status_code == 200
    assert corrected.json()["id"] == first.json()["id"]
    assert corrected.json()["player_id"] == pau["id"]


def test_player_only_reads_own_mvp_recognitions(client, admin_headers) -> None:
    biel = create_player(client, admin_headers, "biel", "biel-player-token")
    pau = create_player(client, admin_headers, "pau", "pau-player-token-")
    event = create_event(client, admin_headers)
    awarded = client.put(
        f"/mvp/{event['id']}/{pau['id']}",
        json={},
        headers=admin_headers,
    ).json()
    headers = {"Authorization": "Bearer biel-player-token"}

    own = client.get(f"/mvp/player/{biel['id']}", headers=headers)
    other = client.get(f"/mvp/player/{pau['id']}", headers=headers)
    match_mvp = client.get(f"/mvp/event/{event['id']}", headers=headers)

    assert awarded["player_id"] == pau["id"]
    assert own.status_code == 200
    assert own.json() == []
    assert other.status_code == 403
    assert match_mvp.status_code == 403


def test_player_cannot_assign_mvp(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    event = create_event(client, admin_headers)

    response = client.put(
        f"/mvp/{event['id']}/{player['id']}",
        json={},
        headers={"Authorization": "Bearer biel-player-token"},
    )

    assert response.status_code == 403


def test_training_cannot_have_mvp(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    event = create_event(client, admin_headers, event_type="training")

    response = client.put(
        f"/mvp/{event['id']}/{player['id']}",
        json={},
        headers=admin_headers,
    )

    assert response.status_code == 400
