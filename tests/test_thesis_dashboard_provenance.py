"""Dashboard provenance filters use existing Thesis records."""

from common.thesis_service import create_thesis


def test_thesis_dashboard_exposes_provenance_filters(dashboard_client, project_id):
    create_thesis(project_id, {})
    response = dashboard_client.get("/thesis?role=scientific_evidence&suggestion_status=approved&q=missing")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Procedencia" in html
    assert 'name="suggestion_status"' in html
    assert 'value="scientific_evidence"' in html
    assert "Sin resultados." in html


def test_thesis_dashboard_has_provenance_columns(dashboard_client, project_id):
    create_thesis(project_id, {})
    response = dashboard_client.get("/thesis")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for label in ("documento", "hash", "fragmentos", "almacenamiento", "Procedencia"):
        assert label in html
