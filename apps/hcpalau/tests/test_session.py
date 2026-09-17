def create_player(client, admin_headers):
    response = client.post(
        "/players",
        json={"slug": "biel", "name": "Biel", "access_token": "biel-player-token"},
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def test_player_session_returns_only_own_safe_profile(client, admin_headers) -> None:
    player = create_player(client, admin_headers)

    response = client.get(
        "/auth/session?jugador=biel",
        headers={"Authorization": "Bearer biel-player-token"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "player"
    assert response.json()["player"]["id"] == player["id"]
    assert response.json()["player"]["slug"] == "biel"
    assert "access_token" not in response.json()["player"]


def test_player_token_cannot_bootstrap_another_slug(client, admin_headers) -> None:
    create_player(client, admin_headers)

    response = client.get(
        "/auth/session?jugador=pau",
        headers={"Authorization": "Bearer biel-player-token"},
    )

    assert response.status_code == 403


def test_admin_session_has_no_player_profile(client, admin_headers) -> None:
    response = client.get("/auth/session", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {"role": "admin", "player": None}


def test_revoked_player_cannot_bootstrap_session(client, admin_headers) -> None:
    player = create_player(client, admin_headers)
    client.patch(
        f"/players/{player['id']}/access",
        json={"access_active": False},
        headers=admin_headers,
    )

    response = client.get(
        "/auth/session?jugador=biel",
        headers={"Authorization": "Bearer biel-player-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Access disabled"
