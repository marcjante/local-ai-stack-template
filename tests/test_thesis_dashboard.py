"""Minimal Dashboard Thesis view over the existing Thesis stores."""

import io

from common.thesis_service import create_thesis
from common.thesis_placements import generate_for_file, list_suggestions
from common.thesis_classifier import classify_file
from rq.job import Job
from workers.queue_conn import redis_conn


def _headers():
    from backend.auth import issue_token
    return {"Authorization": "Bearer " + issue_token("dashboard-test", "admin")}


def test_thesis_dashboard_renders_structure_fragments_and_suggestions(
    dashboard_client, backend_client, project_id
):
    create_thesis(project_id, {"title": "Dashboard thesis"})
    response = backend_client.post(
        f"/api/projects/{project_id}/thesis/files",
        data={"declared_role": "own_results", "files[]": (io.BytesIO(b"x,y\n1,2\n"), "results.csv")},
        headers=_headers(), content_type="multipart/form-data",
    )
    assert response.status_code == 202
    item = response.json["accepted"][0]
    Job.fetch(item["job_id"], connection=redis_conn).perform()
    Job.fetch(item["job_id"] + "-extract", connection=redis_conn).perform()
    classify_file(project_id, item["id"])
    generate_for_file(project_id, item["id"])

    page = dashboard_client.get("/thesis")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Dashboard thesis" in html
    assert "results.csv" in html
    assert "Propuestas de destino" in html
    assert "source_locator" not in html
    assert list_suggestions(project_id)


def test_thesis_dashboard_review_is_project_scoped(dashboard_client, backend_client, project_id):
    create_thesis(project_id, {})
    response = backend_client.post(
        f"/api/projects/{project_id}/thesis/files",
        data={"declared_role": "own_results", "files[]": (io.BytesIO(b"x,y\n1,2\n"), "results.csv")},
        headers=_headers(), content_type="multipart/form-data",
    )
    item = response.json["accepted"][0]
    Job.fetch(item["job_id"], connection=redis_conn).perform()
    Job.fetch(item["job_id"] + "-extract", connection=redis_conn).perform()
    classify_file(project_id, item["id"])
    generate_for_file(project_id, item["id"])
    suggestion = list_suggestions(project_id)[0]

    reviewed = dashboard_client.post(
        f"/thesis/placements/{suggestion['id']}/review",
        data={"status": "approved"},
        headers={"Accept": "application/json"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json == {"updated": suggestion["id"]}
    assert list_suggestions(project_id, status="approved")[0]["reviewer_id"] == "dashboard"
