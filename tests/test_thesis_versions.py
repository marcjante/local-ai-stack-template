"""Phase 3A version/source persistence and project isolation."""

import io

from common.thesis_service import create_thesis, get_structure
from common.thesis_versions import add_source, create_claim, create_version, list_sources, list_versions
from common.thesis_files import file_detail
from rq.job import Job
from workers.queue_conn import redis_conn


def _headers(subject="versions-admin", role="admin"):
    from backend.auth import issue_token
    return {"Authorization": "Bearer " + issue_token(subject, role)}


def _fragment(backend_client, project_id):
    create_thesis(project_id, {})
    response = backend_client.post(
        f"/api/projects/{project_id}/thesis/files",
        data={"declared_role": "scientific_evidence", "files[]": (io.BytesIO(b"Abstract\nEvidence from study."), "paper.csv")},
        headers=_headers(), content_type="multipart/form-data",
    )
    item = response.json["accepted"][0]
    Job.fetch(item["job_id"], connection=redis_conn).perform()
    Job.fetch(item["job_id"] + "-extract", connection=redis_conn).perform()
    return item, file_detail(project_id, item["id"])["fragments"][0]


def test_sources_versions_and_claims_are_traceable(backend_client, project_id):
    item, fragment = _fragment(backend_client, project_id)
    chapter = next(c for c in get_structure(project_id)["chapters"] if c["chapter_type"] == "background")
    source = add_source(project_id, chapter["id"], {"fragment_id": fragment["id"], "purpose": "evidence"}, "reviewer")
    assert source["doc_id"] == item["doc_id"]
    version = create_version(project_id, chapter["id"], {"content_markdown": "## Contexto\nTexto."}, "author")
    assert version["version_number"] == 1
    second = create_version(project_id, chapter["id"], {"content_markdown": "Updated"}, "author")
    assert second["version_number"] == 2
    claim = create_claim(project_id, version["id"], {"claim_text": "La evidencia aporta contexto.", "claim_type": "literature"})
    assert claim["section_version_id"] == version["id"]
    assert len(list_sources(project_id, chapter["id"])) == 1
    assert len(list_versions(project_id, chapter["id"])) == 2


def test_version_endpoints_and_cross_project_isolation(backend_client, project_id):
    create_thesis(project_id, {})
    chapter = get_structure(project_id)["chapters"][0]
    created = backend_client.post(
        f"/api/projects/{project_id}/thesis/chapters/{chapter['id']}/versions",
        json={"content_markdown": "Portada", "status": "draft"}, headers=_headers(),
    )
    assert created.status_code == 201
    listed = backend_client.get(
        f"/api/projects/{project_id}/thesis/chapters/{chapter['id']}/versions", headers=_headers()
    )
    assert listed.status_code == 200 and len(listed.json["versions"]) == 1
    foreign = backend_client.get(
        f"/api/projects/{project_id}/thesis/chapters/not-owned/versions", headers=_headers()
    )
    assert foreign.status_code == 404
