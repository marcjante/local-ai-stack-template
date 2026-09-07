"""test_llm_gateway.py — routing y manejo de proveedores/errores."""

import pytest


@pytest.fixture
def gateway_client():
    import llm_gateway.llm_gateway as gw
    gw.app.testing = True
    return gw.app.test_client()


def test_providers_endpoint_lists_available(gateway_client):
    resp = gateway_client.get("/providers")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "ollama" in data["available"]
    assert "openai_compatible" in data["available"]


def test_unknown_provider_returns_400(gateway_client):
    resp = gateway_client.post("/generate", json={"provider": "no-existe", "prompt": "hola"})
    assert resp.status_code == 400


def test_generate_without_provider_uses_ollama_and_fails_gracefully(gateway_client):
    # Sin Ollama real corriendo, debe fallar con un 502 claro, no un 500 sin explicar
    resp = gateway_client.post("/generate", json={"prompt": "hola"})
    assert resp.status_code in (502, 200)  # 200 si por casualidad hay un Ollama real escuchando
