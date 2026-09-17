def test_player_frontend_is_served(client) -> None:
    response = client.get("/app/")

    assert response.status_code == 200
    assert "HC Palau · Infantil D" in response.text
    assert "Accés desactivat" in response.text


def test_frontend_uses_real_api_and_bearer_token(client) -> None:
    response = client.get("/app/app.js")

    assert response.status_code == 200
    assert 'headers.set("Authorization", `Bearer ${token}`)' in response.text
    assert 'fetch(`${API_BASE}${path}`' in response.text
    assert "/auth/session?jugador=" in response.text


def test_frontend_supports_admin_mode(client) -> None:
    html = client.get("/app/")
    javascript = client.get("/app/app.js")

    assert 'id="admin-portal"' in html.text
    assert 'api("/players")' in javascript.text
    assert 'api("/events")' in javascript.text
    assert 'api("/goals"' in javascript.text
    assert 'session.role === "admin"' in javascript.text


def test_admin_frontend_manages_individual_exercises(client) -> None:
    html = client.get("/app/")
    javascript = client.get("/app/app.js")

    assert 'id="exercise-form"' in html.text
    assert 'id="assignment-form"' in html.text
    assert 'id="video-form"' in html.text
    assert 'api("/exercises"' in javascript.text
    assert "/assign/${form.player_id}" in javascript.text
    assert "/video`" in javascript.text
    assert "assign/all" not in javascript.text
