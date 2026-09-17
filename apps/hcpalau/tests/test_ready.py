from backend.app.database import get_session
from backend.app.main import app


def test_ready_when_database_is_available(client) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "hcpalau"}


def test_ready_returns_503_when_database_query_fails(client, monkeypatch) -> None:
    def failing_session():
        class BrokenSession:
            def exec(self, _query):
                raise RuntimeError("database unavailable")

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        yield BrokenSession()

    app.dependency_overrides[get_session] = failing_session
    try:
        response = client.get("/ready")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "service": "hcpalau"}
