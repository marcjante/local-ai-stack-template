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


def test_admin_frontend_manages_matchday_data(client) -> None:
    html = client.get("/app/")
    javascript = client.get("/app/app.js")

    assert 'id="convocation-form"' in html.text
    assert 'id="mvp-form"' in html.text
    assert 'id="reinforcement-form"' in html.text
    assert "`/convocations/${form.event_id}/${form.player_id}`" in javascript.text
    assert "`/mvp/${form.event_id}/${form.player_id}`" in javascript.text
    assert 'api("/reinforcements"' in javascript.text


def test_admin_frontend_manages_individual_planning(client) -> None:
    html = client.get("/app/")
    javascript = client.get("/app/app.js")

    assert 'id="routine-form"' in html.text
    assert 'id="routine-exercise-form"' in html.text
    assert 'id="exam-form"' in html.text
    assert 'id="follow-up-form"' in html.text
    assert 'api("/routines"' in javascript.text
    assert "`/routines/${routineId}/exercises`" in javascript.text
    assert 'api("/exam-periods"' in javascript.text
    assert 'api("/seguiment"' in javascript.text


def test_frontend_renders_convocations_and_standings(client) -> None:
    html = client.get("/app/")
    javascript = client.get("/app/app.js")

    assert 'data-tab="standings"' in html.text
    assert 'id="standing-form"' in html.text
    assert "api(`/convocations/player/${id}`)" in javascript.text
    assert "api(`/standings?season=${encodeURIComponent(season)}`)" in javascript.text
    assert 'api("/standings"' in javascript.text


def test_admin_frontend_exposes_configurable_whiteboard_link(client) -> None:
    html = client.get("/app/")
    javascript = client.get("/app/app.js")

    assert 'id="whiteboard-link"' in html.text
    assert 'params.get("pissarra")' in javascript.text
    assert "setupWhiteboard()" in javascript.text


def test_admin_polling_does_not_refresh_active_forms(client) -> None:
    javascript = client.get("/app/app.js").text

    assert "adminLoadInFlight" in javascript
    assert 'document.activeElement?.closest("form")' in javascript


def test_admin_poll_interval_is_bounded(client) -> None:
    javascript = client.get("/app/app.js").text

    assert 'params.get("poll")' in javascript
    assert "requestedPollSeconds >= 5" in javascript
    assert "requestedPollSeconds <= 60" in javascript
