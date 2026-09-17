from io import BytesIO


def create_player(client, admin_headers, slug="biel", token="biel-player-token"):
    response = client.post(
        "/players",
        json={"slug": slug, "name": slug.title(), "access_token": token},
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def create_exercise(client, admin_headers):
    response = client.post(
        "/exercises",
        json={"title": "Frenada", "description": "Frenada en paral·lel"},
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def assign_exercise(client, admin_headers, exercise_id, player_id):
    response = client.post(
        f"/exercises/{exercise_id}/assign/{player_id}",
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def test_exercise_assignment_is_individual(client, admin_headers) -> None:
    biel = create_player(client, admin_headers)
    pau = create_player(client, admin_headers, "pau", "pau-player-token-")
    exercise = create_exercise(client, admin_headers)
    assignment = assign_exercise(client, admin_headers, exercise["id"], biel["id"])

    biel_response = client.get(
        f"/exercises/player/{biel['id']}",
        headers={"Authorization": "Bearer biel-player-token"},
    )
    pau_response = client.get(
        f"/exercises/player/{pau['id']}",
        headers={"Authorization": "Bearer pau-player-token-"},
    )

    assert biel_response.json() == [assignment]
    assert pau_response.json() == []


def test_mov_video_is_rejected(client, admin_headers, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HCPALAU_VIDEO_DIR", str(tmp_path))
    exercise = create_exercise(client, admin_headers)

    response = client.post(
        f"/exercises/{exercise['id']}/video",
        files={"video": ("exercise.mov", b"not-a-video", "video/quicktime")},
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert list(tmp_path.iterdir()) == []


def test_video_over_30_mb_is_rejected(client, admin_headers, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HCPALAU_VIDEO_DIR", str(tmp_path))
    exercise = create_exercise(client, admin_headers)
    oversized = BytesIO(b"0" * (30 * 1024 * 1024 + 1))

    response = client.post(
        f"/exercises/{exercise['id']}/video",
        files={"video": ("exercise.mp4", oversized, "video/mp4")},
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert list(tmp_path.iterdir()) == []


def test_progress_never_exceeds_three_per_week(client, admin_headers) -> None:
    player = create_player(client, admin_headers)
    exercise = create_exercise(client, admin_headers)
    assignment = assign_exercise(client, admin_headers, exercise["id"], player["id"])
    headers = {"Authorization": "Bearer biel-player-token"}

    responses = [
        client.post(f"/exercise-progress/{assignment['id']}/increment", headers=headers)
        for _ in range(4)
    ]

    assert [response.status_code for response in responses] == [200, 200, 200, 409]
    assert responses[2].json()["repetitions"] == 3


def test_player_cannot_increment_another_players_assignment(client, admin_headers) -> None:
    biel = create_player(client, admin_headers)
    pau = create_player(client, admin_headers, "pau", "pau-player-token-")
    exercise = create_exercise(client, admin_headers)
    assignment = assign_exercise(client, admin_headers, exercise["id"], pau["id"])

    response = client.post(
        f"/exercise-progress/{assignment['id']}/increment",
        headers={"Authorization": "Bearer biel-player-token"},
    )

    assert biel["id"] != pau["id"]
    assert response.status_code == 403
