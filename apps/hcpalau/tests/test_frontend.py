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
