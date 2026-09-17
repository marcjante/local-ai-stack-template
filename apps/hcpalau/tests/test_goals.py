def create_player(client, admin_headers, slug, token):
    response = client.post(
        "/players",
        json={"slug": slug, "name": slug.title(), "access_token": token},
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def create_goal(client, admin_headers, player_id):
    response = client.post(
        "/goals",
        json={
            "player_id": player_id,
            "title": "Millorar la frenada",
            "description": "Practicar la frenada en paral·lel.",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def test_admin_assigns_goal_to_one_player(client, admin_headers) -> None:
    biel = create_player(client, admin_headers, "biel", "biel-player-token")
    pau = create_player(client, admin_headers, "pau", "pau-player-token-")
    goal = create_goal(client, admin_headers, biel["id"])

    biel_response = client.get(
        f"/goals/player/{biel['id']}",
        headers={"Authorization": "Bearer biel-player-token"},
    )
    pau_response = client.get(
        f"/goals/player/{pau['id']}",
        headers={"Authorization": "Bearer pau-player-token-"},
    )

    assert biel_response.json() == [goal]
    assert pau_response.json() == []


def test_player_cannot_read_or_update_another_players_goal(client, admin_headers) -> None:
    biel = create_player(client, admin_headers, "biel", "biel-player-token")
    pau = create_player(client, admin_headers, "pau", "pau-player-token-")
    goal = create_goal(client, admin_headers, pau["id"])
    headers = {"Authorization": "Bearer biel-player-token"}

    list_response = client.get(f"/goals/player/{pau['id']}", headers=headers)
    update_response = client.patch(
        f"/goals/{goal['id']}/done",
        json={"done": True},
        headers=headers,
    )

    assert biel["id"] != pau["id"]
    assert list_response.status_code == 403
    assert update_response.status_code == 403


def test_player_cannot_reopen_completed_goal(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    goal = create_goal(client, admin_headers, player["id"])
    headers = {"Authorization": "Bearer biel-player-token"}

    completed = client.patch(
        f"/goals/{goal['id']}/done",
        json={"done": True},
        headers=headers,
    )
    reopened = client.patch(
        f"/goals/{goal['id']}/done",
        json={"done": False},
        headers=headers,
    )

    assert completed.status_code == 200
    assert completed.json()["done"] is True
    assert completed.json()["done_at"] is not None
    assert reopened.status_code == 403


def test_admin_can_correct_completed_goal(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    goal = create_goal(client, admin_headers, player["id"])
    client.patch(
        f"/goals/{goal['id']}/done",
        json={"done": True},
        headers=admin_headers,
    )

    response = client.patch(
        f"/goals/{goal['id']}/done",
        json={"done": False},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["done"] is False
    assert response.json()["done_at"] is None
