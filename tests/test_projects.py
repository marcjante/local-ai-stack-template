"""test_projects.py — CRUD de proyectos y su configuración."""

from db.db import (
    get_project, get_project_settings, update_project_settings,
    list_projects, task_counts_by_status,
)


def test_project_created_with_default_settings(project_id):
    project = get_project(project_id)
    assert project is not None
    assert project["id"] == project_id

    settings = get_project_settings(project_id)
    assert settings is not None
    assert settings["temperature"] == 0.4
    assert settings["chunk_size"] == 120


def test_project_appears_in_list(project_id):
    ids = [p["id"] for p in list_projects()]
    assert project_id in ids


def test_update_project_settings(project_id):
    update_project_settings(project_id, default_model="llama3.1:8b", temperature=0.9)
    settings = get_project_settings(project_id)
    assert settings["default_model"] == "llama3.1:8b"
    assert settings["temperature"] == 0.9


def test_task_counts_scoped_to_project(project_id):
    from db.db import create_task
    create_task("t1-" + project_id, "process", {}, project_id=project_id)
    counts = task_counts_by_status(project_id=project_id)
    assert counts.get("pending") == 1

    # Otro proyecto no debe ver esta tarea
    from db.db import create_project
    other = project_id + "-other"
    create_project(other, "Otro")
    other_counts = task_counts_by_status(project_id=other)
    assert other_counts.get("pending", 0) == 0

    from db.db import get_conn
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM tasks WHERE id = %s", ("t1-" + project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (other,))
