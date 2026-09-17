def create_player(client, admin_headers, slug, token):
    response = client.post(
        "/players",
        json={"slug": slug, "name": slug.title(), "access_token": token},
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def create_follow_up(client, admin_headers, player_id, note, visible):
    response = client.post(
        "/seguiment",
        json={
            "player_id": player_id,
            "observed_on": "2026-09-17",
            "category": "technical",
            "note": note,
            "visible_to_player": visible,
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def test_player_only_sees_own_visible_follow_up(client, admin_headers) -> None:
    biel = create_player(client, admin_headers, "biel", "biel-player-token")
    pau = create_player(client, admin_headers, "pau", "pau-player-token-")
    visible = create_follow_up(client, admin_headers, biel["id"], "Bona frenada", True)
    create_follow_up(client, admin_headers, biel["id"], "Nota interna", False)
    create_follow_up(client, admin_headers, pau["id"], "Nota de Pau", True)

    response = client.get(
        f"/seguiment/player/{biel['id']}",
        headers={"Authorization": "Bearer biel-player-token"},
    )

    assert response.status_code == 200
    assert response.json() == [visible]


def test_admin_sees_visible_and_internal_follow_up(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    visible = create_follow_up(client, admin_headers, player["id"], "Visible", True)
    internal = create_follow_up(client, admin_headers, player["id"], "Interna", False)

    response = client.get(f"/seguiment/player/{player['id']}", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == [visible, internal]


def test_player_cannot_read_another_players_follow_up(client, admin_headers) -> None:
    biel = create_player(client, admin_headers, "biel", "biel-player-token")
    pau = create_player(client, admin_headers, "pau", "pau-player-token-")
    create_follow_up(client, admin_headers, pau["id"], "Visible", True)

    response = client.get(
        f"/seguiment/player/{pau['id']}",
        headers={"Authorization": "Bearer biel-player-token"},
    )

    assert biel["id"] != pau["id"]
    assert response.status_code == 403


def test_player_cannot_create_or_delete_follow_up(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    follow_up = create_follow_up(client, admin_headers, player["id"], "Visible", True)
    headers = {"Authorization": "Bearer biel-player-token"}

    create_response = client.post(
        "/seguiment",
        json={
            "player_id": player["id"],
            "observed_on": "2026-09-17",
            "category": "technical",
            "note": "No autoritzada",
            "visible_to_player": True,
        },
        headers=headers,
    )
    delete_response = client.delete(f"/seguiment/{follow_up['id']}", headers=headers)

    assert create_response.status_code == 403
    assert delete_response.status_code == 403
