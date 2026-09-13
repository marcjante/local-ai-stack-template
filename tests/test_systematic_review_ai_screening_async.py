"""
Tests del lanzamiento asíncrono del screening IA.

Comprueba que el dashboard:
- crea una tarea RQ sin ejecutar el LLM dentro de la petición HTTP;
- evita dos screenings simultáneos para la misma revisión;
- detecta cuando no quedan artículos pendientes;
- respeta el aislamiento entre proyectos al consultar tareas.
"""

import uuid

from db.db import create_project, create_task, get_conn, get_task


def _insert_review(project_id, *, with_article=True, ai_decision=None):
    review_id = f"review-{uuid.uuid4().hex}"
    article_id = f"article-{uuid.uuid4().hex}"

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
            VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            """,
            (
                review_id,
                project_id,
                "Revisión para test screening IA asíncrono",
                "systematic_review",
                "¿Las intervenciones digitales mejoran la adherencia?",
                "Pacientes con tuberculosis",
                "Intervenciones de salud digital",
                "Atención habitual",
                "Adherencia al tratamiento",
                "Estudios de tuberculosis con intervención digital.",
                "Estudios sin tuberculosis o sin intervención digital.",
                "screening",
            ),
        )

        if with_article:
            cur.execute(
                """
                INSERT INTO review_articles (
                    id,
                    review_id,
                    title,
                    abstract,
                    ai_decision
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    article_id,
                    review_id,
                    "Digital health intervention for tuberculosis adherence",
                    "Abstract de prueba para screening IA.",
                    ai_decision,
                ),
            )

    return review_id, article_id


class FakeQueue:
    enqueued = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def enqueue(self, func, task_id, payload, **kwargs):
        self.__class__.enqueued.append(
            {
                "func": func,
                "task_id": task_id,
                "payload": payload,
                "kwargs": kwargs,
            }
        )


def test_ai_screening_is_enqueued_asynchronously(
    dashboard_client,
    project_id,
    monkeypatch,
):
    import dashboard.dashboard_service as dash

    review_id, _ = _insert_review(project_id)

    FakeQueue.enqueued = []
    monkeypatch.setattr(dash, "Queue", FakeQueue)

    response = dashboard_client.post(
        "/api/systematic-review/ai-screening",
        json={"review_id": review_id},
    )

    assert response.status_code == 202, response.get_data(as_text=True)

    payload = response.get_json()

    assert payload["ok"] is True
    assert payload["queue"] == "screening"
    assert payload["status"] == "pending"
    assert payload["pending_articles"] == 1
    assert payload["task_id"]

    # La petición HTTP solo debe encolar el trabajo.
    assert len(FakeQueue.enqueued) == 1

    queued = FakeQueue.enqueued[0]

    assert queued["task_id"] == payload["task_id"]
    assert queued["payload"]["review_id"] == review_id
    assert queued["payload"]["project_id"] == project_id

    task = get_task(payload["task_id"])

    assert task is not None
    assert task["queue"] == "screening"
    assert task["status"] == "pending"
    assert task["project_id"] == project_id


def test_ai_screening_reuses_existing_active_task(
    dashboard_client,
    project_id,
    monkeypatch,
):
    import dashboard.dashboard_service as dash

    review_id, _ = _insert_review(project_id)

    existing_task_id = f"task-{uuid.uuid4().hex}"

    create_task(
        existing_task_id,
        "screening",
        {
            "review_id": review_id,
            "project_id": project_id,
        },
        project_id=project_id,
    )

    FakeQueue.enqueued = []
    monkeypatch.setattr(dash, "Queue", FakeQueue)

    response = dashboard_client.post(
        "/api/systematic-review/ai-screening",
        json={"review_id": review_id},
    )

    assert response.status_code == 202, response.get_data(as_text=True)

    payload = response.get_json()

    assert payload["ok"] is True
    assert payload["already_running"] is True
    assert payload["task_id"] == existing_task_id
    assert payload["status"] == "pending"

    # No debe crear un segundo job RQ.
    assert FakeQueue.enqueued == []


def test_ai_screening_returns_no_pending_when_articles_already_screened(
    dashboard_client,
    project_id,
    monkeypatch,
):
    import dashboard.dashboard_service as dash

    review_id, _ = _insert_review(
        project_id,
        ai_decision="include",
    )

    FakeQueue.enqueued = []
    monkeypatch.setattr(dash, "Queue", FakeQueue)

    response = dashboard_client.post(
        "/api/systematic-review/ai-screening",
        json={"review_id": review_id},
    )

    assert response.status_code == 200, response.get_data(as_text=True)

    payload = response.get_json()

    assert payload["ok"] is True
    assert payload["no_pending"] is True
    assert payload["screened"] == 0
    assert payload["status"] == "completed"

    assert FakeQueue.enqueued == []


def test_ai_screening_task_status_is_project_scoped(
    dashboard_client,
    project_id,
):
    other_project_id = f"other-{uuid.uuid4().hex}"

    create_project(
        other_project_id,
        "Proyecto ajeno para test",
    )

    review_id, _ = _insert_review(
        other_project_id,
        with_article=False,
    )

    task_id = f"task-{uuid.uuid4().hex}"

    create_task(
        task_id,
        "screening",
        {
            "review_id": review_id,
            "project_id": other_project_id,
        },
        project_id=other_project_id,
    )

    try:
        response = dashboard_client.get(
            f"/api/systematic-review/tasks/{task_id}"
        )

        assert response.status_code == 404

        payload = response.get_json()
        assert payload["ok"] is False

    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tasks WHERE project_id = %s",
                (other_project_id,),
            )
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
