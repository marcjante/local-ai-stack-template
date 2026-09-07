"""test_health.py — que cada servicio responda lo que dice responder."""


def test_backend_health(backend_client):
    resp = backend_client.get("/health")
    assert resp.status_code == 200


def test_backend_ready_checks_dependencies(backend_client):
    resp = backend_client.get("/ready")
    assert resp.status_code in (200, 503)  # 503 si Redis/Postgres no están, pero responde


def test_backend_requires_api_key(backend_client):
    resp = backend_client.post("/enqueue/fetch", json={})
    assert resp.status_code == 401


def test_dashboard_onboarding_reachable(dashboard_client):
    resp = dashboard_client.get("/onboarding")
    assert resp.status_code == 200
