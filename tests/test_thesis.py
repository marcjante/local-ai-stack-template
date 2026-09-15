"""Phase 1A integration tests against the same PostgreSQL as the existing suite."""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.config import Config
from alembic.script import ScriptDirectory
import psycopg2
import pytest
import sqlalchemy as sa

from common import thesis_service as thesis
from db.db import DB_DSN, add_project_member, get_conn


def _headers(subject="thesis-admin", role="admin"):
    from backend.auth import issue_token

    return {"Authorization": "Bearer " + issue_token(subject, role)}


def _url(project_id, suffix=""):
    return f"/api/projects/{project_id}/thesis{suffix}"


def test_creation_and_initial_order(backend_client, project_id):
    response = backend_client.post(_url(project_id), json={"title": "Mi tesis"}, headers=_headers())
    assert response.status_code == 201
    assert response.json["created"] is True
    profile = response.json["profile"]
    assert profile["project_id"] == project_id
    assert profile["title"] == "Mi tesis"
    assert profile["language"] == "es"
    assert profile["created_at"] and profile["updated_at"]
    structure = backend_client.get(_url(project_id, "/structure"), headers=_headers())
    assert structure.status_code == 200
    chapters = structure.json["chapters"]
    assert [(c["chapter_type"], c["title"]) for c in chapters] == list(thesis.INITIAL_CHAPTERS)
    assert [c["order_index"] for c in chapters] == list(range(1, 17))
    assert all(c["project_id"] == project_id and c["parent_id"] is None for c in chapters)
    assert all(c["status"] == "empty" and c["approved_version_id"] is None for c in chapters)


def test_repeated_creation_preserves_profile_and_renamed_chapters(backend_client, project_id):
    first = backend_client.post(_url(project_id), json={"title": "Original"}, headers=_headers())
    chapters = thesis.get_structure(project_id)["chapters"]
    thesis.update_chapter_title(project_id, chapters[8]["id"], "Hallazgos")
    thesis.update_chapter_title(project_id, chapters[7]["id"], "Material y métodos")
    repeated = backend_client.post(_url(project_id), json={"title": "No sobrescribir"}, headers=_headers())
    assert repeated.status_code == 200
    assert repeated.json["created"] is False
    assert repeated.json["profile"] == first.json["profile"]
    current = thesis.get_structure(project_id)["chapters"]
    assert [c["id"] for c in current] == [c["id"] for c in chapters]
    assert current[8]["title"] == "Hallazgos"
    assert current[8]["chapter_type"] == "results"
    assert current[7]["title"] == "Material y métodos"
    assert current[7]["chapter_type"] == "methods"


def test_concurrent_creation_is_idempotent(project_id):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: thesis.create_thesis(project_id, {}), range(4)))
    assert sum(created for _, created in results) == 1
    assert len({p["id"] for p, _ in results}) == 1
    assert len(thesis.get_structure(project_id)["chapters"]) == 16


def test_profile_update_is_partial(backend_client, project_id):
    original, _ = thesis.create_thesis(project_id, {"title": "Título", "author": "Autora"})
    data = {"university": "Universidad", "program": "Doctorado", "supervisors": "Directora",
            "language": "ca", "citation_style": "vancouver", "template": "doctoral"}
    response = backend_client.put(_url(project_id, "/profile"), json=data, headers=_headers())
    assert response.status_code == 200
    updated = response.json["profile"]
    assert all(updated[k] == v for k, v in data.items())
    assert updated["title"] == "Título" and updated["author"] == "Autora"
    assert updated["id"] == original["id"]
    assert thesis.get_structure(project_id)["profile"]["updated_at"] >= original["updated_at"]
    response = backend_client.put(_url(project_id, "/profile"), json={"author": None}, headers=_headers())
    assert response.status_code == 200 and response.json["profile"]["author"] is None


@pytest.mark.parametrize("payload", [[], None, {"project_id": "other"}, {"language": " "},
                                      {"title": 1}, {"title": None}, {"author": ["a"]}])
def test_invalid_profile_is_400(backend_client, project_id, payload):
    import json
    for method, suffix in (("post", ""), ("put", "/profile")):
        response = getattr(backend_client, method)(
            _url(project_id, suffix), data=json.dumps(payload),
            content_type="application/json", headers=_headers(),
        )
        assert response.status_code == 400
        assert "error" in response.json


@pytest.mark.parametrize("method,suffix", [("post", ""), ("get", "/structure"), ("put", "/profile")])
def test_missing_project_is_404(backend_client, method, suffix):
    response = getattr(backend_client, method)(_url("missing-" + uuid.uuid4().hex, suffix),
                                               json={}, headers=_headers())
    assert response.status_code == 404
    assert response.json == {"error": "proyecto no encontrado"}


@pytest.mark.parametrize("method,suffix", [("get", "/structure"), ("put", "/profile")])
def test_missing_thesis_is_404(backend_client, project_id, method, suffix):
    response = getattr(backend_client, method)(_url(project_id, suffix), json={}, headers=_headers())
    assert response.status_code == 404
    assert response.json == {"error": "tesis no encontrada"}


@pytest.mark.parametrize("method,suffix", [("post", ""), ("get", "/structure"), ("put", "/profile")])
def test_authentication_and_cross_project_access(backend_client, project_id, method, suffix):
    other = project_id + "-other"
    # Clean up the additional project explicitly, including the new FK cascades.
    from db.db import create_project
    create_project(other, "Other Thesis")
    try:
        thesis.create_thesis(project_id, {"title": "Privada"})
        thesis.create_thesis(other, {"title": "Otra"})
        add_project_member(project_id, "thesis-editor", "editor")
        action = getattr(backend_client, method)
        assert action(_url(project_id, suffix), json={}).status_code == 401
        headers = _headers("thesis-editor", "lector")
        assert action(_url(other, suffix), json={}, headers=headers).status_code == 403
        assert action(_url(project_id, suffix), json={}, headers=headers).status_code == 200
        assert thesis.get_structure(other)["profile"]["title"] == "Otra"
        foreign_chapter = thesis.get_structure(other)["chapters"][0]
        with pytest.raises(thesis.ThesisNotFound):
            thesis.update_chapter_title(project_id, foreign_chapter["id"], "Intrusión")
        assert thesis.get_structure(other)["chapters"][0]["title"] == "Portada"
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (other,))


def test_viewer_can_only_read(backend_client, project_id):
    thesis.create_thesis(project_id, {})
    add_project_member(project_id, "thesis-viewer", "viewer")
    headers = _headers("thesis-viewer", "lector")
    assert backend_client.get(_url(project_id, "/structure"), headers=headers).status_code == 200
    assert backend_client.post(_url(project_id), json={}, headers=headers).status_code == 403
    assert backend_client.put(_url(project_id, "/profile"), json={}, headers=headers).status_code == 403


@pytest.mark.parametrize("error,status", [(psycopg2.IntegrityError, 409), (psycopg2.OperationalError, 500)])
def test_database_errors_are_json(backend_client, project_id, monkeypatch, error, status):
    def fail(*args):
        raise error("private database details")
    monkeypatch.setattr(thesis, "create_thesis", fail)
    response = backend_client.post(_url(project_id), json={}, headers=_headers())
    assert response.status_code == status
    assert "error" in response.json
    assert "private" not in response.get_data(as_text=True)


def test_malformed_json(backend_client, project_id):
    for content_type in ("application/json", "text/plain"):
        response = backend_client.post(_url(project_id), data="{", content_type=content_type,
                                       headers=_headers())
        assert response.status_code == 400 and "error" in response.json


def test_subsections_order_and_parent_isolation(project_id):
    thesis.create_thesis(project_id, {})
    chapters = thesis.get_structure(project_id)["chapters"]
    methods = chapters[7]
    with get_conn() as conn, conn.cursor() as cur:
        for order in (2, 1):
            cur.execute(
                "INSERT INTO thesis_chapters (id, project_id, parent_id, code, title, chapter_type, order_index) "
                "VALUES (%s, %s, %s, %s, %s, 'methods', %s)",
                (str(uuid.uuid4()), project_id, methods["id"], f"methods.{order}", f"Apartado {order}", order),
            )
    structure = thesis.get_structure(project_id)["chapters"]
    assert [c["code"] for c in structure[7:11]] == ["methods", "methods.1", "methods.2", "results"]
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        with get_conn() as conn, conn.cursor() as cur:
            # Valid parent ID paired with another project must be rejected by PostgreSQL.
            other = project_id + "-foreign"
            cur.execute("INSERT INTO projects (id, name) VALUES (%s, 'Foreign')", (other,))
            cur.execute("INSERT INTO thesis_profiles (id, project_id) VALUES (%s, %s)", (other, other))
            cur.execute(
                "INSERT INTO thesis_chapters (id, project_id, parent_id, code, title, chapter_type, order_index) "
                "VALUES (%s, %s, %s, 'bad', 'Bad', 'methods', 1)",
                (other, other, methods["id"]),
            )


def test_creation_rolls_back_on_chapter_failure(project_id, monkeypatch):
    monkeypatch.setattr(thesis, "INITIAL_CHAPTERS", (("cover", "Portada"), ("cover", "Duplicado")))
    with pytest.raises(psycopg2.IntegrityError):
        thesis.create_thesis(project_id, {})
    with get_conn() as conn, conn.cursor() as cur:
        for table in ("thesis_profiles", "thesis_chapters"):
            cur.execute(f"SELECT count(*) FROM {table} WHERE project_id = %s", (project_id,))
            assert cur.fetchone()[0] == 0


def test_migration_upgrade_downgrade_and_constraints():
    """Exercise real DDL in a private schema, rolled back even on assertion failure."""
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_heads() == ["e4f5a6b7c8d9"]
    assert scripts.get_revision("e4f5a6b7c8d9").down_revision == "d3e4f12b9c07"
    migration_path = Path("db/migrations/versions/f1a7c93d820b_add_thesis_profiles_and_chapters.py")
    spec = importlib.util.spec_from_file_location("thesis_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "ee1060d265ac"
    engine = sa.create_engine("postgresql+psycopg2://", creator=lambda: psycopg2.connect(DB_DSN))
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                schema = "thesis_test_" + uuid.uuid4().hex
                connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
                connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
                connection.exec_driver_sql("CREATE TABLE projects (id TEXT PRIMARY KEY)")
                with Operations.context(MigrationContext.configure(connection)):
                    migration.upgrade()
                    inspector = sa.inspect(connection)
                    assert set(inspector.get_table_names(schema=schema)) == {
                        "projects", "thesis_profiles", "thesis_chapters",
                    }
                    fks = inspector.get_foreign_keys("thesis_chapters", schema=schema)
                    assert any(fk["constrained_columns"] == ["project_id", "parent_id"] for fk in fks)
                    assert inspector.get_indexes("thesis_chapters", schema=schema)
                    dates = {c["name"]: c for c in inspector.get_columns("thesis_profiles", schema=schema)}
                    assert dates["created_at"]["type"].timezone
                    assert not dates["updated_at"]["nullable"]
                    migration.downgrade()
                    assert sa.inspect(connection).get_table_names(schema=schema) == ["projects"]
                    migration.upgrade()
                    assert "thesis_chapters" in sa.inspect(connection).get_table_names(schema=schema)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
