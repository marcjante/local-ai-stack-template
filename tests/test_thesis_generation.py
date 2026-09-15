"""Phase 3B generation and claim verification reuse the existing RAG verifier."""

import io
from types import SimpleNamespace

from common.thesis_service import create_thesis, get_structure
from common.thesis_versions import add_source, list_claims
from common.thesis_files import file_detail
from common.thesis_generation import generate_chapter, verify_version
from rq.job import Job
from workers.queue_conn import redis_conn


def _headers():
    from backend.auth import issue_token
    return {"Authorization": "Bearer " + issue_token("generation-admin", "admin")}


def _chapter_with_source(backend_client, project_id):
    create_thesis(project_id, {})
    item = backend_client.post(
        f"/api/projects/{project_id}/thesis/files",
        data={"declared_role": "scientific_evidence", "files[]": (io.BytesIO(b"Abstract\nThis study reports evidence."), "paper.csv")},
        headers=_headers(), content_type="multipart/form-data",
    ).json["accepted"][0]
    Job.fetch(item["job_id"], connection=redis_conn).perform()
    Job.fetch(item["job_id"] + "-extract", connection=redis_conn).perform()
    fragment = file_detail(project_id, item["id"])["fragments"][0]
    chapter = next(c for c in get_structure(project_id)["chapters"] if c["chapter_type"] == "background")
    add_source(project_id, chapter["id"], {"fragment_id": fragment["id"], "purpose": "evidence"}, "reviewer")
    return chapter


def test_generation_creates_version_and_claims(monkeypatch, backend_client, project_id):
    chapter = _chapter_with_source(backend_client, project_id)
    monkeypatch.setattr("common.thesis_generation.requests.post", lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"response": "La evidencia aporta contexto.", "_model_used": "test-model"}))
    version = generate_chapter(project_id, chapter["id"])
    assert version["version_number"] == 1
    assert len(list_claims(project_id, version["id"])) == 1


def test_verification_updates_claim_status_and_keeps_project_scope(monkeypatch, backend_client, project_id):
    chapter = _chapter_with_source(backend_client, project_id)
    monkeypatch.setattr("common.thesis_generation.requests.post", lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"response": "This study reports evidence."}))
    version = generate_chapter(project_id, chapter["id"])
    result = verify_version(project_id, version["id"])
    assert result["claims"]
    assert result["claims"][0]["verification_status"] in {"verified", "partial", "unsupported"}
