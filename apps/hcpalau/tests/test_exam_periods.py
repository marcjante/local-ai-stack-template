def create_player(client, admin_headers, slug, token):
    response = client.post(
        "/players",
        json={"slug": slug, "name": slug.title(), "access_token": token},
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def create_period(client, admin_headers, player_id):
    return client.post(
        "/exam-periods",
        json={
            "player_id": player_id,
            "start_date": "2026-10-19",
            "end_date": "2026-10-23",
            "note": "Setmana d'exàmens",
        },
        headers=admin_headers,
    )


def test_admin_creates_individual_exam_period(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")

    created = create_period(client, admin_headers, player["id"])
    listed = client.get(
        f"/exam-periods/player/{player['id']}",
        headers={"Authorization": "Bearer biel-player-token"},
    )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json() == [created.json()]


def test_player_cannot_read_another_players_exam_period(client, admin_headers) -> None:
    biel = create_player(client, admin_headers, "biel", "biel-player-token")
    pau = create_player(client, admin_headers, "pau", "pau-player-token-")
    assert create_period(client, admin_headers, pau["id"]).status_code == 201

    response = client.get(
        f"/exam-periods/player/{pau['id']}",
        headers={"Authorization": "Bearer biel-player-token"},
    )

    assert biel["id"] != pau["id"]
    assert response.status_code == 403


def test_player_cannot_create_or_delete_exam_period(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    period = create_period(client, admin_headers, player["id"]).json()
    headers = {"Authorization": "Bearer biel-player-token"}

    create_response = client.post(
        "/exam-periods",
        json={
            "player_id": player["id"],
            "start_date": "2026-11-02",
            "end_date": "2026-11-06",
        },
        headers=headers,
    )
    delete_response = client.delete(f"/exam-periods/{period['id']}", headers=headers)

    assert create_response.status_code == 403
    assert delete_response.status_code == 403


def test_exam_period_rejects_reversed_dates(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")

    response = client.post(
        "/exam-periods",
        json={
            "player_id": player["id"],
            "start_date": "2026-10-23",
            "end_date": "2026-10-19",
        },
        headers=admin_headers,
    )

    assert response.status_code == 400
