import uuid

from db.db import get_conn


def _insert_review(project_id):
    review_id = f"review-{uuid.uuid4().hex}"

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO systematic_reviews (
                id,
                project_id,
                title,
                review_type,
                research_question,
                population,
                intervention,
                comparator,
                outcomes,
                inclusion_criteria,
                exclusion_criteria,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                review_id,
                project_id,
                "Protocol update test",
                "systematic_review",
                "Pregunta inicial",
                "Población inicial",
                "Intervención inicial",
                "Comparador inicial",
                "Outcome inicial",
                "Inclusión inicial",
                "Exclusión inicial",
                "screening",
            ),
        )

    return review_id


def test_protocol_update_persists_fields(
    dashboard_client,
    project_id,
):
    review_id = _insert_review(project_id)

    response = dashboard_client.post(
        "/api/systematic-review/update-protocol",
        json={
            "review_id": review_id,
            "research_question": "Nueva pregunta",
            "population": "Nueva población",
            "intervention": "Nueva intervención",
            "comparator": "Nuevo comparador",
            "outcomes": "Nuevos outcomes",
            "inclusion_criteria": "Nuevos criterios de inclusión",
            "exclusion_criteria": "Nuevos criterios de exclusión",
        },
    )

    assert response.status_code == 200, response.get_data(as_text=True)

    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["review_id"] == review_id

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                research_question,
                population,
                intervention,
                comparator,
                outcomes,
                inclusion_criteria,
                exclusion_criteria
            FROM systematic_reviews
            WHERE id = %s
            """,
            (review_id,),
        )

        row = cur.fetchone()

    assert row == (
        "Nueva pregunta",
        "Nueva población",
        "Nueva intervención",
        "Nuevo comparador",
        "Nuevos outcomes",
        "Nuevos criterios de inclusión",
        "Nuevos criterios de exclusión",
    )


def test_protocol_update_requires_review_id(
    dashboard_client,
):
    response = dashboard_client.post(
        "/api/systematic-review/update-protocol",
        json={
            "research_question": "Pregunta sin review_id",
        },
    )

    assert response.status_code == 400

    payload = response.get_json()
    assert payload["ok"] is False
    assert "review_id" in payload["error"]


def test_protocol_update_is_project_scoped(
    dashboard_client,
    project_id,
):
    other_project_id = f"other-{uuid.uuid4().hex}"

    from db.db import create_project

    create_project(
        other_project_id,
        "Proyecto ajeno",
    )

    review_id = _insert_review(other_project_id)

    try:
        response = dashboard_client.post(
            "/api/systematic-review/update-protocol",
            json={
                "review_id": review_id,
                "research_question": "Intento de modificación",
                "population": "",
                "intervention": "",
                "comparator": "",
                "outcomes": "",
                "inclusion_criteria": "",
                "exclusion_criteria": "",
            },
        )

        assert response.status_code == 404

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT research_question
                FROM systematic_reviews
                WHERE id = %s
                """,
                (review_id,),
            )

            assert cur.fetchone()[0] == "Pregunta inicial"

    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM systematic_reviews WHERE project_id = %s",
                (other_project_id,),
            )
            cur.execute(
                "DELETE FROM project_settings WHERE project_id = %s",
                (other_project_id,),
            )
            cur.execute(
                "DELETE FROM projects WHERE id = %s",
                (other_project_id,),
            )


def test_protocol_update_creates_reproducibility_audit(
    dashboard_client,
    project_id,
):
    review_id = _insert_review(project_id)

    response = dashboard_client.post(
        "/api/systematic-review/update-protocol",
        json={
            "review_id": review_id,
            "research_question": "Pregunta auditada",
            "population": "Población auditada",
            "intervention": "Intervención auditada",
            "comparator": "Comparador auditado",
            "outcomes": "Outcomes auditados",
            "inclusion_criteria": "Inclusión auditada",
            "exclusion_criteria": "Exclusión auditada",
        },
    )

    assert response.status_code == 200, response.get_data(as_text=True)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                action,
                actor_type,
                before_state,
                after_state,
                details
            FROM review_audit_log
            WHERE review_id = %s
              AND action = 'protocol_updated'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (review_id,),
        )
        audit = cur.fetchone()

    assert audit is not None
    assert audit[0] == "protocol_updated"
    assert audit[1] == "human"

    before_state = audit[2]
    after_state = audit[3]
    details = audit[4]

    assert before_state["research_question"] == "Pregunta inicial"
    assert after_state["research_question"] == "Pregunta auditada"
    assert after_state["inclusion_criteria"] == "Inclusión auditada"
    assert details["source"] == "systematic_review_protocol_editor"
