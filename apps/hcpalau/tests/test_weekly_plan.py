def test_admin_can_create_weekly_plan_and_player_reads_it(client, admin_headers) -> None:
    player = client.post("/players", headers=admin_headers, json={"slug": "biel", "name": "Biel", "access_token": "biel-player-token"}).json()
    exercise = client.post("/exercises", headers=admin_headers, json={"title": "Estirament obligatori"}).json()
    created = client.post("/weekly-plan", headers=admin_headers, json={"player_id": player["id"], "exercise_id": exercise["id"], "week_start": "2026-09-14", "mandatory": True})
    assert created.status_code == 201
    rows = client.get("/weekly-plan/player/1?week_start=2026-09-14", headers={"Authorization": "Bearer biel-player-token"})
    assert rows.status_code == 200
    assert rows.json()[0]["mandatory"] is True
