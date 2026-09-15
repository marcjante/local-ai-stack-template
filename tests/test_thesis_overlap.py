"""Deterministic Thesis overlap warnings use project fragments only."""

import io
from common.thesis_service import create_thesis, get_structure
from common.thesis_versions import add_source, create_version
from common.thesis_files import file_detail
from common.thesis_overlap import check_version, get_check
from rq.job import Job
from workers.queue_conn import redis_conn


def _headers():
    from backend.auth import issue_token
    return {"Authorization": "Bearer " + issue_token("overlap-admin", "admin")}


def test_overlap_check_is_project_scoped_and_repeatable(backend_client, project_id):
    create_thesis(project_id, {})
    item = backend_client.post(
        f"/api/projects/{project_id}/thesis/files",
        data={"declared_role": "own_results", "files[]": (io.BytesIO(b"text,value\nThe study reports evidence and results.,1\n"), "results.csv")},
        headers=_headers(), content_type="multipart/form-data",
    ).json["accepted"][0]
    Job.fetch(item["job_id"], connection=redis_conn).perform()
    Job.fetch(item["job_id"] + "-extract", connection=redis_conn).perform()
    fragment = file_detail(project_id, item["id"])["fragments"][0]
    chapter = next(c for c in get_structure(project_id)["chapters"] if c["chapter_type"] == "results")
    add_source(project_id, chapter["id"], {"fragment_id": fragment["id"], "purpose": "data"}, "reviewer")
    version = create_version(project_id, chapter["id"], {"content_markdown": "The study reports evidence and results."}, "author")
    first = check_version(project_id, version["id"], "reviewer")
    second = check_version(project_id, version["id"], "reviewer")
    assert first["max_score"] > 0.8
    assert second["id"] == first["id"]
    assert get_check(project_id, version["id"])["project_id"] == project_id
