"""Dashboard entry point for existing Thesis classification and placement services."""

import io

from common.thesis_service import create_thesis
from common.thesis_placements import list_suggestions
from rq.job import Job
from workers.queue_conn import redis_conn


def _headers():
    from backend.auth import issue_token
    return {"Authorization": "Bearer " + issue_token("dashboard-classifier", "admin")}


def test_dashboard_classifies_file_and_creates_idempotent_suggestions(
    dashboard_client, backend_client, project_id
):
    create_thesis(project_id, {})
    response = backend_client.post(
        f"/api/projects/{project_id}/thesis/files",
        data={"declared_role": "own_results", "files[]": (io.BytesIO(b"results\np-value\n0.02\n"), "results.csv")},
        headers=_headers(), content_type="multipart/form-data",
    )
    item = response.json["accepted"][0]
    Job.fetch(item["job_id"], connection=redis_conn).perform()
    Job.fetch(item["job_id"] + "-extract", connection=redis_conn).perform()

    first = dashboard_client.post(
        f"/thesis/files/{item['id']}/classify", headers={"Accept": "application/json"}
    )
    second = dashboard_client.post(
        f"/thesis/files/{item['id']}/classify", headers={"Accept": "application/json"}
    )
    assert first.status_code == second.status_code == 200
    assert first.json["placement"]["suggestions_created"] > 0
    assert second.json["placement"]["suggestions_created"] == 0
    assert list_suggestions(project_id)
