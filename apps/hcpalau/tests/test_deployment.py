from pathlib import Path


APP_ROOT = Path(__file__).parents[1]


def test_container_includes_alembic_configuration_and_migrations() -> None:
    dockerfile = (APP_ROOT / "Dockerfile").read_text()

    assert "COPY alembic.ini ./" in dockerfile
    assert "COPY backend ./backend" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "/ready" in dockerfile
    assert (APP_ROOT / "alembic.ini").is_file()
    assert list((APP_ROOT / "backend" / "migrations" / "versions").glob("*.py"))
