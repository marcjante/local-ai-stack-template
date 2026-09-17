PLAYER = {
    "slug": "biel",
    "name": "Biel",
    "access_token": "biel-player-token",
}


def create_player(client, admin_headers):
    response = client.post("/players", json=PLAYER, headers=admin_headers)
    assert response.status_code == 201
    return response.json()


def test_admin_can_create_and_list_players(client, admin_headers) -> None:
    created = create_player(client, admin_headers)

    response = client.get("/players", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == [created]


def test_player_can_read_self_but_not_another_player(client, admin_headers) -> None:
    biel = create_player(client, admin_headers)
    second = dict(PLAYER, slug="pau", name="Pau", access_token="pau-player-token-")
    pau = client.post("/players", json=second, headers=admin_headers).json()
    player_headers = {"Authorization": f"Bearer {PLAYER['access_token']}"}

    own_response = client.get(f"/players/{biel['id']}", headers=player_headers)
    other_response = client.get(f"/players/{pau['id']}", headers=player_headers)

    assert own_response.status_code == 200
    assert "access_token" not in own_response.json()
    assert other_response.status_code == 403


def test_revoking_access_blocks_player_immediately(client, admin_headers) -> None:
    player = create_player(client, admin_headers)
    player_headers = {"Authorization": f"Bearer {PLAYER['access_token']}"}
    assert client.get(f"/players/{player['id']}", headers=player_headers).status_code == 200

    revoke = client.patch(
        f"/players/{player['id']}/access",
        json={"access_active": False},
        headers=admin_headers,
    )
    blocked = client.get(f"/players/{player['id']}", headers=player_headers)

    assert revoke.status_code == 200
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Access disabled"


def test_player_cannot_use_admin_endpoints(client, admin_headers) -> None:
    create_player(client, admin_headers)
    player_headers = {"Authorization": f"Bearer {PLAYER['access_token']}"}

    assert client.get("/players", headers=player_headers).status_code == 403
    assert client.post("/players", json=PLAYER, headers=player_headers).status_code == 403
