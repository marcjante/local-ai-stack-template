"""
Tests del flujo de screening humano para revisiones sistemáticas.
Valida: Revisor 1 + Revisor 2 -> conflicto -> adjudicación -> resolución.
"""

import uuid
from db.db import get_conn


def _insert_review_and_article(project_id):
    review_id = f"review-{uuid.uuid4().hex}"
    article_id = f"article-{uuid.uuid4().hex}"

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO systematic_reviews (
                id, project_id, title, review_type, research_question,
                inclusion_criteria, exclusion_criteria, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                review_id,
                project_id,
                "Test screening con adjudicación",
                "systematic_review",
                "¿Funciona correctamente el flujo de doble revisor?",
                "Artículos relevantes para la pregunta.",
                "Artículos no relevantes para la pregunta.",
                "screening",
            ),
        )
        cur.execute(
            """
            INSERT INTO review_articles (id, review_id, title, abstract)
            VALUES (%s, %s, %s, %s)
            """,
            (
                article_id,
                review_id,
                "Artículo de prueba para screening",
                "Resumen creado exclusivamente para un test automatizado.",
            ),
        )

    return review_id, article_id


def test_screening_conflict_and_adjudication(dashboard_client, project_id):
    review_id, article_id = _insert_review_and_article(project_id)

    response = dashboard_client.post(
        "/api/systematic-review/human-decision",
        json={
            "review_id": review_id,
            "article_id": article_id,
            "reviewer_id": "reviewer_1",
            "stage": "title_abstract",
            "decision": "include",
            "notes": "Revisor 1: incluir.",
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM review_screening_conflicts
            WHERE article_id = %s
              AND stage = 'title_abstract'
              AND status = 'open'
            """,
            (article_id,),
        )
        assert cur.fetchone()[0] == 0

    response = dashboard_client.post(
        "/api/systematic-review/human-decision",
        json={
            "review_id": review_id,
            "article_id": article_id,
            "reviewer_id": "reviewer_2",
            "stage": "title_abstract",
            "decision": "exclude",
            "exclusion_reason_code": "NOT_RELEVANT",
            "exclusion_reason": "No cumple los criterios de inclusión.",
            "notes": "Revisor 2: excluir.",
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT reviewer_id, decision
            FROM review_screening_decisions
            WHERE article_id = %s
              AND stage = 'title_abstract'
            ORDER BY reviewer_id
            """,
            (article_id,),
        )
        assert cur.fetchall() == [
            ("reviewer_1", "include"),
            ("reviewer_2", "exclude"),
        ]

        cur.execute(
            """
            SELECT status, resolution, resolved_by
            FROM review_screening_conflicts
            WHERE article_id = %s
              AND stage = 'title_abstract'
            """,
            (article_id,),
        )
        assert cur.fetchone() == ("open", None, None)

        cur.execute(
            """
            SELECT title_abstract_status
            FROM review_articles
            WHERE id = %s
            """,
            (article_id,),
        )
        assert cur.fetchone()[0] == "conflict"

    response = dashboard_client.post(
        "/api/systematic-review/resolve-conflict",
        json={
            "review_id": review_id,
            "article_id": article_id,
            "stage": "title_abstract",
            "resolution": "include",
            "resolved_by": "adjudicator",
            "resolution_notes": "Incluido tras adjudicación.",
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, resolution, resolved_by, resolution_notes, resolved_at
            FROM review_screening_conflicts
            WHERE article_id = %s
              AND stage = 'title_abstract'
            """,
            (article_id,),
        )
        conflict = cur.fetchone()
        assert conflict[0] == "resolved"
        assert conflict[1] == "include"
        assert conflict[2] == "adjudicator"
        assert conflict[3] == "Incluido tras adjudicación."
        assert conflict[4] is not None

        cur.execute(
            """
            SELECT
                title_abstract_status,
                full_text_status,
                human_decision,
                screening_status,
                screening_stage,
                exclusion_reason,
                exclusion_reason_code
            FROM review_articles
            WHERE id = %s
            """,
            (article_id,),
        )
        article = cur.fetchone()

        assert article[0] == "include"
        assert article[1] == "pending"
        assert article[2] == "include"
        assert article[3] == "reviewed"
        assert article[4] == "title_abstract"
        assert article[5] is None
        assert article[6] is None

def test_adjudicator_cannot_submit_normal_screening_decision(
    dashboard_client,
    project_id,
):
    review_id, article_id = _insert_review_and_article(project_id)

    response = dashboard_client.post(
        "/api/systematic-review/human-decision",
        json={
            "review_id": review_id,
            "article_id": article_id,
            "reviewer_id": "adjudicator",
            "stage": "title_abstract",
            "decision": "include",
        },
    )

    assert response.status_code == 400

    payload = response.get_json()
    assert payload["ok"] is False
    assert "solo puede resolver conflictos" in payload["error"]

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM review_screening_decisions
            WHERE article_id = %s
              AND reviewer_id = 'adjudicator'
            """,
            (article_id,),
        )
        assert cur.fetchone()[0] == 0


def test_ai_screening_continues_after_malformed_model_response(
    project_id,
    monkeypatch,
):
    from db.db import create_task
    from workers.plugins import screening

    review_id, failed_article_id = _insert_review_and_article(project_id)

    successful_article_id = f"article-{uuid.uuid4().hex}"
    task_id = f"screening-test-{uuid.uuid4().hex}"

    # Aseguramos un orden determinista:
    # primero se procesa el artículo que fallará.
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE review_articles
            SET created_at = now() - interval '1 minute'
            WHERE id = %s
            """,
            (failed_article_id,),
        )

        cur.execute(
            """
            INSERT INTO review_articles (
                id,
                review_id,
                title,
                abstract
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                successful_article_id,
                review_id,
                "Artículo que debe procesarse después del fallo",
                "Este artículo debe recibir una decisión IA válida.",
            ),
        )

    create_task(
        task_id,
        "screening",
        {"review_id": review_id},
        project_id=project_id,
    )

    # Secuencia simulada del modelo:
    # 1) artículo 1: JSON inválido
    # 2) reintento estricto artículo 1: vuelve a fallar
    # 3) artículo 2: JSON válido
    model_responses = iter([
        {
            "response": "Esto no es JSON válido."
        },
        {
            "response": "Sigo sin devolver JSON válido."
        },
        {
            "response": """
            {
                "decision": "include",
                "reason": "Cumple aparentemente los criterios.",
                "confidence": 0.91
            }
            """,
            "_model_used": "test-model",
            "_provider_used": "test-provider",
        },
    ])

    calls = []

    def fake_call_screening_model(prompt, strict_retry=False):
        calls.append(strict_retry)
        return next(model_responses)

    monkeypatch.setattr(
        screening,
        "_call_screening_model",
        fake_call_screening_model,
    )

    result = screening.handle(
        task_id,
        {"review_id": review_id},
    )

    # El lote no debe abortar por el primer artículo.
    assert result["screened"] == 1
    assert result["failed"] == 1

    assert len(result["results"]) == 1
    assert len(result["errors"]) == 1

    assert result["errors"][0]["article_id"] == failed_article_id
    assert result["results"][0]["article_id"] == successful_article_id

    # Primer artículo:
    # intento normal + reintento estricto.
    # Segundo artículo:
    # intento normal.
    assert calls == [False, True, False]

    with get_conn() as conn, conn.cursor() as cur:
        # El artículo fallido debe quedar SIN decisión para poder reintentarlo.
        cur.execute(
            """
            SELECT ai_decision, ai_reason, ai_confidence
            FROM review_articles
            WHERE id = %s
            """,
            (failed_article_id,),
        )
        failed_article = cur.fetchone()

        assert failed_article[0] is None
        assert failed_article[1] is None
        assert failed_article[2] is None

        # El segundo artículo sí debe haberse guardado correctamente.
        cur.execute(
            """
            SELECT
                ai_decision,
                ai_reason,
                ai_confidence,
                screening_stage
            FROM review_articles
            WHERE id = %s
            """,
            (successful_article_id,),
        )
        successful_article = cur.fetchone()

        assert successful_article[0] == "include"
        assert successful_article[1] == "Cumple aparentemente los criterios."
        assert successful_article[2] == 0.91
        assert successful_article[3] == "title_abstract"

        # Aunque un artículo haya fallado, el batch debe terminar.
        cur.execute(
            """
            SELECT status
            FROM tasks
            WHERE id = %s
            """,
            (task_id,),
        )
        assert cur.fetchone()[0] == "completed"
