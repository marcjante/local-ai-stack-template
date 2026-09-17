def test_player_can_mark_home_exercise_done_or_not(client, admin_headers) -> None:
    player = client.post("/players", headers=admin_headers, json={"slug": "biel", "name": "Biel", "access_token": "biel-player-token"}).json()
    exercise = client.post("/exercises", headers=admin_headers, json={"title": "Planxa", "description": "30 segons"}).json()
    headers = {"Authorization": "Bearer biel-player-token"}

    saved = client.patch(f"/exercise-checkins/{player['id']}/{exercise['id']}", headers=headers, json={"completed": True})
    assert saved.status_code == 200
    assert saved.json()["completed"] is True
    listed = client.get(f"/exercise-checkins/player/{player['id']}", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["exercise_id"] == exercise["id"]


def test_player_cannot_mark_another_players_home_exercise(client, admin_headers) -> None:
    biel = client.post("/players", headers=admin_headers, json={"slug": "biel", "name": "Biel", "access_token": "biel-player-token"}).json()
    pau = client.post("/players", headers=admin_headers, json={"slug": "pau", "name": "Pau", "access_token": "pau-player-token"}).json()
    exercise = client.post("/exercises", headers=admin_headers, json={"title": "Planxa", "description": "30 segons"}).json()
    response = client.patch(f"/exercise-checkins/{pau['id']}/{exercise['id']}", headers={"Authorization": "Bearer biel-player-token"}, json={"completed": False})
    assert biel["id"] != pau["id"]
    assert response.status_code == 403
