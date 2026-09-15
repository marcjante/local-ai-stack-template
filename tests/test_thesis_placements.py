"""1B2b placement generation and human review."""

import io

from common.thesis_service import create_thesis, get_structure
from common.thesis_placements import generate_for_file, list_suggestions
from common.thesis_classifier import classify_file
from db.db import create_project, get_conn
from rq.job import Job
from workers.queue_conn import redis_conn


def _headers(subject="placement-admin", role="admin"):
    from backend.auth import issue_token
    return {"Authorization": "Bearer " + issue_token(subject, role)}


def _upload(client, project_id, text=b"Results\nvalue,p-value\n12,0.03\n"):
    return client.post(
        f"/api/projects/{project_id}/thesis/files",
        data={"declared_role": "own_results", "files[]": (io.BytesIO(text), "results.csv")},
        headers=_headers(), content_type="multipart/form-data",
    )


def _extract(item, project_id):
    Job.fetch(item["job_id"], connection=redis_conn).perform()
    Job.fetch(item["job_id"] + "-extract", connection=redis_conn).perform()
    classify_file(project_id, item["id"])
    generate_for_file(project_id, item["id"])


def test_generation_is_idempotent_and_targets_existing_chapters(backend_client, project_id):
    create_thesis(project_id, {})
    response = _upload(backend_client, project_id)
    assert response.status_code == 202
    item = response.json["accepted"][0]
    _extract(item, project_id)
    first = list_suggestions(project_id)
    second = generate_for_file(project_id, item["id"])
    assert second["suggestions_created"] == 0
    assert list_suggestions(project_id) == first
    assert any(row["chapter_code"] == "results" and row["status"] == "pending" for row in first)
    assert all(row["confidence"] <= 1 for row in first)


def test_review_approved_corrected_and_rejected_is_project_scoped(backend_client, project_id):
    create_thesis(project_id, {})
    item = _upload(backend_client, project_id).json["accepted"][0]
    _extract(item, project_id)
    suggestions = list_suggestions(project_id)
    assert suggestions
    suggestion = suggestions[0]
    chapters = get_structure(project_id)["chapters"]
    corrected = next(chapter for chapter in chapters if chapter["chapter_type"] == "discussion")
    denied = backend_client.put(
        f"/api/projects/{project_id}/thesis/placements/{suggestion['id']}",
        json={"status": "approved"}, headers=_headers("reviewer-1", "lector"),
    )
    assert denied.status_code == 403
    approved = backend_client.put(
        f"/api/projects/{project_id}/thesis/placements/{suggestion['id']}",
        json={"status": "corrected", "corrected_chapter_id": corrected["id"]},
        headers=_headers("reviewer-1", "admin"),
    )
    assert approved.status_code == 200
    assert approved.json["status"] == "corrected"
    assert approved.json["corrected_chapter_id"] == corrected["id"]
    assert approved.json["reviewer_id"] == "reviewer-1"
    rejected = next(row for row in suggestions if row["id"] != suggestion["id"])
    result = backend_client.put(
        f"/api/projects/{project_id}/thesis/placements/{rejected['id']}",
        json={"status": "rejected"}, headers=_headers("reviewer-2", "admin"),
    )
    assert result.status_code == 200 and result.json["status"] == "rejected"


def test_cross_project_chapter_and_suggestion_are_rejected(backend_client, project_id):
    create_thesis(project_id, {})
    other = project_id + "-other"
    create_project(other, "Other")
    create_thesis(other, {})
    try:
        item = _upload(backend_client, project_id).json["accepted"][0]
        _extract(item, project_id)
        suggestion = list_suggestions(project_id)[0]
        foreign_chapter = get_structure(other)["chapters"][0]
        response = backend_client.put(
            f"/api/projects/{project_id}/thesis/placements/{suggestion['id']}",
            json={"status": "corrected", "corrected_chapter_id": foreign_chapter["id"]},
            headers=_headers(),
        )
        assert response.status_code == 404
    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id=%s", (other,))


def test_invalid_review_status_is_json_400(backend_client, project_id):
    create_thesis(project_id, {})
    item = _upload(backend_client, project_id).json["accepted"][0]
    _extract(item, project_id)
    suggestion = list_suggestions(project_id)[0]
    response = backend_client.put(
        f"/api/projects/{project_id}/thesis/placements/{suggestion['id']}",
        json={"status": "pending"}, headers=_headers(),
    )
    assert response.status_code == 400 and "error" in response.json
