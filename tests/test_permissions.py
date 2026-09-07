"""
test_permissions.py

Jerarquía de permisos por proyecto (admin > editor > viewer), vía el
backend real (Flask test client) — no llamadas directas a funciones,
para probar también la capa de autenticación JWT + decodificación.
"""

import json

from db.db import add_project_member


def _token(client, subject, role="lector"):
    resp = client.post(
        "/auth/token",
        headers={"X-API-Key": "test-key"},
        json={"subject": subject, "role": role},
    )
    assert resp.status_code in (200, 202)
    return resp.get_json()["token"]


def test_no_membership_gets_403(backend_client, project_id):
    token = _token(backend_client, "usuario-sin-permiso")
    resp = backend_client.post(
        f"/projects/{project_id}/enqueue/fetch",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert resp.status_code == 403


def test_editor_can_enqueue(backend_client, project_id):
    add_project_member(project_id, "editor-user", "editor")
    token = _token(backend_client, "editor-user")
    resp = backend_client.post(
        f"/projects/{project_id}/enqueue/fetch",
        headers={"Authorization": f"Bearer {token}"},
        json={"source": "x"},
    )
    assert resp.status_code in (200, 202)
    assert resp.get_json()["status"] == "pending"


def test_viewer_cannot_enqueue_but_can_list_members(backend_client, project_id):
    add_project_member(project_id, "viewer-user", "viewer")
    token = _token(backend_client, "viewer-user")

    resp = backend_client.post(
        f"/projects/{project_id}/enqueue/fetch",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert resp.status_code == 403

    resp = backend_client.get(
        f"/projects/{project_id}/members",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (200, 202)


def test_viewer_cannot_add_members(backend_client, project_id):
    add_project_member(project_id, "viewer-user-2", "viewer")
    token = _token(backend_client, "viewer-user-2")

    resp = backend_client.post(
        f"/projects/{project_id}/members",
        headers={"Authorization": f"Bearer {token}"},
        json={"username": "intruso", "role": "admin"},
    )
    assert resp.status_code == 403


def test_global_admin_bypasses_project_membership(backend_client, project_id):
    token = _token(backend_client, "el-jefe", role="admin")
    resp = backend_client.post(
        f"/projects/{project_id}/enqueue/fetch",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert resp.status_code in (200, 202)
