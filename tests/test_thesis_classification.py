"""1B2a classification is deterministic, project-scoped and repeatable."""

import io
import uuid

from common.thesis_classifier import classify_file
from common.thesis_service import create_thesis
from common import thesis_files
from db.db import get_conn
from rq.job import Job
from workers.queue_conn import redis_conn


def _headers():
    from backend.auth import issue_token
    return {"Authorization": "Bearer " + issue_token("classifier-admin", "admin")}


def test_classify_declared_role_and_fragment_content(backend_client, project_id):
    create_thesis(project_id, {})
    response = backend_client.post(
        f"/api/projects/{project_id}/thesis/files",
        data={"declared_role": "own_results", "files[]": (io.BytesIO(b"value,p-value\n12,0.03\n"), "results.csv")},
        headers=_headers(), content_type="multipart/form-data",
    )
    assert response.status_code == 202
    item = response.json["accepted"][0]
    # Extraction worker is queued by the upload; run both real RQ jobs.
    Job.fetch(item["job_id"], connection=redis_conn).perform()
    Job.fetch(item["job_id"] + "-extract", connection=redis_conn).perform()
    result = classify_file(project_id, item["id"])
    assert result["fragment_count"] == 1
    detail = thesis_files.file_detail(project_id, item["id"])
    fragment = detail["fragments"][0]
    assert fragment["source_role"] == "own_results"
    assert fragment["content_type"] == "numeric_results"
    assert fragment["classification_status"] == "classified"
    assert fragment["classification_confidence"] == 1.0
    assert fragment["classifier_version"] == "heuristic-1"
    assert "declarado" in fragment["classification_reason"]


def test_unknown_role_is_classified_and_retry_is_idempotent(backend_client, project_id):
    create_thesis(project_id, {})
    response = backend_client.post(
        f"/api/projects/{project_id}/thesis/files",
        data={"files[]": (io.BytesIO(b"Abstract\nA randomized journal study with DOI: 10.1000/x."), "paper.csv")},
        headers=_headers(), content_type="multipart/form-data",
    )
    item = response.json["accepted"][0]
    Job.fetch(item["job_id"], connection=redis_conn).perform()
    Job.fetch(item["job_id"] + "-extract", connection=redis_conn).perform()
    first = backend_client.post(
        f"/api/projects/{project_id}/thesis/files/{item['id']}/classify", headers=_headers(), json={}
    )
    second = backend_client.post(
        f"/api/projects/{project_id}/thesis/files/{item['id']}/classify", headers=_headers(), json={}
    )
    assert first.status_code == second.status_code == 200
    assert first.json["file_id"] == second.json["file_id"]
    assert first.json["fragment_count"] == second.json["fragment_count"]
    assert first.json["roles"] == second.json["roles"]
    assert first.json["placement"]["suggestions_created"] == 1
    assert second.json["placement"]["suggestions_created"] == 0
    detail = thesis_files.file_detail(project_id, item["id"])
    assert detail["fragments"][0]["source_role"] == "scientific_evidence"
    assert detail["fragments"][0]["classification_confidence"] >= 0.75
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM thesis_fragments WHERE project_id=%s AND doc_id=%s", (project_id, item["doc_id"]))
        assert cur.fetchone()[0] == 1


def test_classifier_does_not_create_placement_suggestions(backend_client, project_id):
    create_thesis(project_id, {})
    response = backend_client.post(
        f"/api/projects/{project_id}/thesis/files",
        data={"declared_role": "scientific_evidence", "files[]": (io.BytesIO(b"Introduction\nContext."), "paper.csv")},
        headers=_headers(), content_type="multipart/form-data",
    )
    assert response.status_code == 202
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.thesis_placement_suggestions')")
        assert cur.fetchone()[0] == "thesis_placement_suggestions"
        cur.execute("SELECT count(*) FROM thesis_placement_suggestions WHERE project_id=%s", (project_id,))
        assert cur.fetchone()[0] == 0
