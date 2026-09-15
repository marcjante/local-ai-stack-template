"""Dashboard editing of visible Thesis chapter titles."""

from common.thesis_service import create_thesis, get_structure


def test_dashboard_updates_title_and_preserves_semantic_type(dashboard_client, project_id):
    create_thesis(project_id, {})
    chapter = get_structure(project_id)["chapters"][8]
    response = dashboard_client.post(
        f"/thesis/chapters/{chapter['id']}/title",
        data={"title": "Resultados principales"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    assert response.json["chapter"]["title"] == "Resultados principales"
    assert response.json["chapter"]["chapter_type"] == "results"

    updated = get_structure(project_id)["chapters"][8]
    assert updated["title"] == "Resultados principales"
    assert updated["chapter_type"] == "results"


def test_dashboard_rejects_foreign_or_empty_title(dashboard_client, project_id):
    create_thesis(project_id, {})
    chapter = get_structure(project_id)["chapters"][0]
    empty = dashboard_client.post(
        f"/thesis/chapters/{chapter['id']}/title",
        data={"title": "   "},
        headers={"Accept": "application/json"},
    )
    assert empty.status_code == 400

    foreign = dashboard_client.post(
        "/thesis/chapters/not-in-project/title",
        data={"title": "Intrusión"},
        headers={"Accept": "application/json"},
    )
    assert foreign.status_code == 404
