def standing(team, position, points):
    return {
        "season": "2026-27",
        "team": team,
        "position": position,
        "played": 4,
        "won": points // 3,
        "drawn": points % 3,
        "lost": 0,
        "goals_for": 12,
        "goals_against": 5,
        "points": points,
    }


def create_player(client, admin_headers):
    response = client.post(
        "/players",
        json={"slug": "biel", "name": "Biel", "access_token": "biel-player-token"},
        headers=admin_headers,
    )
    assert response.status_code == 201


def test_admin_upserts_and_player_reads_ordered_standings(client, admin_headers) -> None:
    create_player(client, admin_headers)
    second = client.post(
        "/standings", json=standing("HC Palau", 2, 9), headers=admin_headers
    )
    first = client.post(
        "/standings", json=standing("CP Vic", 1, 12), headers=admin_headers
    )
    updated_payload = standing("HC Palau", 2, 10)
    updated = client.post("/standings", json=updated_payload, headers=admin_headers)

    response = client.get(
        "/standings?season=2026-27",
        headers={"Authorization": "Bearer biel-player-token"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["id"] == second.json()["id"]
    assert [row["team"] for row in response.json()] == ["CP Vic", "HC Palau"]
    assert response.json()[1]["points"] == 10


def test_player_cannot_write_standings(client, admin_headers) -> None:
    create_player(client, admin_headers)

    response = client.post(
        "/standings",
        json=standing("HC Palau", 1, 12),
        headers={"Authorization": "Bearer biel-player-token"},
    )

    assert response.status_code == 403


def test_two_teams_cannot_share_position_in_same_season(client, admin_headers) -> None:
    assert client.post(
        "/standings", json=standing("HC Palau", 1, 12), headers=admin_headers
    ).status_code == 200

    response = client.post(
        "/standings", json=standing("CP Vic", 1, 10), headers=admin_headers
    )

    assert response.status_code == 409


def test_standings_reject_negative_statistics(client, admin_headers) -> None:
    payload = standing("HC Palau", 1, 12)
    payload["goals_against"] = -1

    response = client.post("/standings", json=payload, headers=admin_headers)

    assert response.status_code == 422
