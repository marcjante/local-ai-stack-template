def create_player(client, admin_headers, slug, token):
    response = client.post(
        "/players",
        json={"slug": slug, "name": slug.title(), "access_token": token},
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def create_exercise(client, admin_headers, title):
    response = client.post(
        "/exercises",
        json={"title": title},
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def create_routine(client, admin_headers, player_id):
    response = client.post(
        "/routines",
        json={"player_id": player_id, "title": "Rutina de patinatge"},
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()


def test_admin_builds_ordered_individual_routine(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    first_exercise = create_exercise(client, admin_headers, "Frenada")
    second_exercise = create_exercise(client, admin_headers, "Creuats")
    routine = create_routine(client, admin_headers, player["id"])
    second = client.post(
        f"/routines/{routine['id']}/exercises",
        json={"exercise_id": second_exercise["id"], "position": 2, "target_repetitions": 2},
        headers=admin_headers,
    )
    first = client.post(
        f"/routines/{routine['id']}/exercises",
        json={"exercise_id": first_exercise["id"], "position": 1, "target_repetitions": 3},
        headers=admin_headers,
    )

    response = client.get(
        f"/routines/{routine['id']}/exercises",
        headers={"Authorization": "Bearer biel-player-token"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert [item["position"] for item in response.json()] == [1, 2]


def test_player_only_reads_own_routines(client, admin_headers) -> None:
    biel = create_player(client, admin_headers, "biel", "biel-player-token")
    pau = create_player(client, admin_headers, "pau", "pau-player-token-")
    pau_routine = create_routine(client, admin_headers, pau["id"])
    headers = {"Authorization": "Bearer biel-player-token"}

    own = client.get(f"/routines/player/{biel['id']}", headers=headers)
    other = client.get(f"/routines/player/{pau['id']}", headers=headers)
    other_items = client.get(f"/routines/{pau_routine['id']}/exercises", headers=headers)

    assert own.status_code == 200
    assert own.json() == []
    assert other.status_code == 403
    assert other_items.status_code == 403


def test_player_cannot_create_or_modify_routine(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    exercise = create_exercise(client, admin_headers, "Frenada")
    routine = create_routine(client, admin_headers, player["id"])
    headers = {"Authorization": "Bearer biel-player-token"}

    create_response = client.post(
        "/routines",
        json={"player_id": player["id"], "title": "No autoritzada"},
        headers=headers,
    )
    modify_response = client.post(
        f"/routines/{routine['id']}/exercises",
        json={"exercise_id": exercise["id"], "position": 1},
        headers=headers,
    )

    assert create_response.status_code == 403
    assert modify_response.status_code == 403


def test_routine_rejects_duplicate_position(client, admin_headers) -> None:
    player = create_player(client, admin_headers, "biel", "biel-player-token")
    first_exercise = create_exercise(client, admin_headers, "Frenada")
    second_exercise = create_exercise(client, admin_headers, "Creuats")
    routine = create_routine(client, admin_headers, player["id"])
    client.post(
        f"/routines/{routine['id']}/exercises",
        json={"exercise_id": first_exercise["id"], "position": 1},
        headers=admin_headers,
    )

    response = client.post(
        f"/routines/{routine['id']}/exercises",
        json={"exercise_id": second_exercise["id"], "position": 1},
        headers=admin_headers,
    )

    assert response.status_code == 409
