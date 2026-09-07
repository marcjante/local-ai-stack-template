"""
conftest.py

Fixtures compartidas. Los tests corren contra Postgres y Redis reales
(no mocks) — igual que se ha probado todo a lo largo de este proyecto.
Necesitan las variables de entorno de siempre (DATABASE_URL o el DSN
por defecto de db.db, y Redis en 127.0.0.1:6379).
"""

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.db import init_schema, get_conn  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Se asegura de que el esquema existe antes de cualquier test."""
    init_schema()


@pytest.fixture
def project_id():
    """Un project_id único por test, para no chocar entre tests que corren en paralelo."""
    pid = f"test-{uuid.uuid4().hex[:8]}"
    from db.db import create_project
    create_project(pid, f"Test {pid}")
    yield pid
    # limpieza: borra el proyecto y todo lo que cuelgue de él
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM documents WHERE project_id = %s", (pid,))
        cur.execute("DELETE FROM tasks WHERE project_id = %s", (pid,))
        cur.execute("DELETE FROM collections WHERE project_id = %s", (pid,))
        cur.execute("DELETE FROM project_members WHERE project_id = %s", (pid,))
        cur.execute("DELETE FROM evaluations WHERE project_id = %s", (pid,))
        cur.execute("DELETE FROM n8n_integrations WHERE project_id = %s", (pid,))
        cur.execute("DELETE FROM project_settings WHERE project_id = %s", (pid,))
        cur.execute("DELETE FROM projects WHERE id = %s", (pid,))


@pytest.fixture
def backend_client(monkeypatch):
    """Cliente de test del backend Flask, con API_KEY conocida."""
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    import importlib
    import backend.main as backend_main
    importlib.reload(backend_main)
    backend_main.app.testing = True
    return backend_main.app.test_client()


@pytest.fixture
def dashboard_client():
    """Cliente de test del panel Flask."""
    import dashboard.dashboard_service as dash
    dash.app.testing = True
    dash.app.secret_key = "test"
    with dash.app.test_client() as client:
        yield client
