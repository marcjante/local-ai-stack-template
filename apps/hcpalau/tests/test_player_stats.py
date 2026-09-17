def create_player(client, admin_headers, slug, token):
    response = client.post(
        "/players",
        json={"slug": slug, "name": slug.title(), "access_token": token},
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def increment(client, admin_headers, player_id, source_key, goals):
    return client.post(
        f"/player-stats/{player_id}/increment",
        json={
            "season": "2026-27",
            "source_key": source_key,
            "games": 1,
            "goals": goals,
            "assists": 1,
        },
        headers=admin_headers,
    )


def test_stats_are_summed_and_never_overwritten(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")

    first = increment(client, admin_headers, player["id"], "fecapa-act-100", 2)
    second = increment(client, admin_headers, player["id"], "fecapa-act-101", 1)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["games"] == 2
    assert second.json()["goals"] == 3
    assert second.json()["assists"] == 2


def test_repeated_source_is_idempotent(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")

    first = increment(client, admin_headers, player["id"], "fecapa-act-100", 2)
    repeated = increment(client, admin_headers, player["id"], "fecapa-act-100", 2)

    assert repeated.status_code == 200
    assert repeated.json()["id"] == first.json()["id"]
    assert repeated.json()["games"] == 1
    assert repeated.json()["goals"] == 2


def test_player_only_reads_own_stats(client, admin_headers) -> None:
    biel = create_player(client, admin_headers, "biel", "biel-player-token")
    pau = create_player(client, admin_headers, "pau", "pau-player-token-")
    increment(client, admin_headers, pau["id"], "fecapa-act-100", 1)
    headers = {"Authorization": "Bearer biel-player-token"}

    own = client.get(f"/player-stats/player/{biel['id']}", headers=headers)
    other = client.get(f"/player-stats/player/{pau['id']}", headers=headers)

    assert own.status_code == 200
    assert own.json() == []
    assert other.status_code == 403


def test_player_cannot_increment_stats(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")

    response = increment(
        client,
        {"Authorization": "Bearer biel-player-token"},
        player["id"],
        "manual-1",
        1,
    )

    assert response.status_code == 403


def test_negative_stat_increment_is_rejected(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")

    response = increment(client, admin_headers, player["id"], "manual-1", -1)

    assert response.status_code == 422
