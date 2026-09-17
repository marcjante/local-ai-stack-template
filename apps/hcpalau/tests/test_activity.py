def test_activity_is_admin_only(client, admin_headers) -> None:
    assert client.get("/activity").status_code == 401
    assert client.get("/activity", headers=admin_headers).status_code == 200


def test_player_attendance_appears_in_coach_activity(client, admin_headers) -> None:
    player = client.post(
        "/players",
        headers=admin_headers,
        json={"slug": "activity-player", "name": "Activity Player", "access_token": "activity-player-token"},
    ).json()
    event = client.post(
        "/events",
        headers=admin_headers,
        json={"title": "Entrenament activitat", "starts_at": "2026-09-20T10:00:00Z", "event_type": "training"},
    ).json()

    saved = client.patch(
        f"/attendance/{event['id']}/{player['id']}",
        headers={"Authorization": "Bearer activity-player-token"},
        json={"attending": False, "absence_reason": "Lesió al turmell"},
    )
    assert saved.status_code == 200

    activity = client.get("/activity", headers=admin_headers)

    assert activity.status_code == 200
    assert any(item["kind"] == "attendance" and item["player"] == "Activity Player" and item["reason"] == "Lesió al turmell" for item in activity.json())
