import uuid

from db.db import create_project, get_conn


def _create_review_and_article(project_id):
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
                inclusion_criteria,
                exclusion_criteria,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                review_id,
                project_id,
                "Project isolation test review",
                "systematic_review",
                "Does project isolation work?",
                "Include relevant studies.",
                "Exclude irrelevant studies.",
                "screening",
            ),
        )

        cur.execute(
            """
            INSERT INTO review_articles (
                id,
                review_id,
                title,
                abstract,
                screening_status,
                title_abstract_status,
                full_text_status,
                full_text_retrieval_status,
                full_text_available
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                'reviewed',
                'include',
                'pending',
                'not_sought',
                FALSE
            )
            """,
            (
                article_id,
                review_id,
                "Isolation test article",
                "Article belonging to project A.",
            ),
        )

    return review_id, article_id


def _create_extraction(review_id, article_id):
    field_id = f"field-{uuid.uuid4().hex}"
    extraction_id = f"extraction-{uuid.uuid4().hex}"

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO review_extraction_fields (
                id,
                review_id,
                field_key,
                label,
                value_type,
                required,
                display_order
            )
            VALUES (%s, %s, %s, %s, %s, FALSE, 1)
            """,
            (
                field_id,
                review_id,
                "sample_size",
                "Sample size",
                "text",
            ),
        )

        cur.execute(
            """
            INSERT INTO review_extractions (
                id,
                review_id,
                article_id,
                field_id,
                ai_value,
                validation_status
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s::json,
                'pending'
            )
            """,
            (
                extraction_id,
                review_id,
                article_id,
                field_id,
                '"100"',
            ),
        )

    return extraction_id


def _select_project(client, project_id):
    with client.session_transaction() as sess:
        sess["project_id"] = project_id


def _cleanup_project(project_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM systematic_reviews
            WHERE project_id = %s
            """,
            (project_id,),
        )

        cur.execute(
            """
            DELETE FROM project_settings
            WHERE project_id = %s
            """,
            (project_id,),
        )

        cur.execute(
            """
            DELETE FROM project_members
            WHERE project_id = %s
            """,
            (project_id,),
        )

        cur.execute(
            """
            DELETE FROM projects
            WHERE id = %s
            """,
            (project_id,),
        )


def test_project_b_cannot_submit_human_decision_for_project_a(
    dashboard_client,
):
    project_a = f"project-a-{uuid.uuid4().hex[:8]}"
    project_b = f"project-b-{uuid.uuid4().hex[:8]}"

    create_project(project_a, "Project A")
    create_project(project_b, "Project B")

    review_id, article_id = _create_review_and_article(project_a)

    try:
        _select_project(dashboard_client, project_b)

        response = dashboard_client.post(
            "/api/systematic-review/human-decision",
            json={
                "review_id": review_id,
                "article_id": article_id,
                "reviewer_id": "reviewer_1",
                "stage": "title_abstract",
                "decision": "include",
            },
        )

        assert response.status_code == 404

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM review_screening_decisions
                WHERE article_id = %s
                """,
                (article_id,),
            )
            assert cur.fetchone()[0] == 0

    finally:
        _cleanup_project(project_a)
        _cleanup_project(project_b)


def test_project_b_cannot_change_full_text_retrieval_for_project_a(
    dashboard_client,
):
    project_a = f"project-a-{uuid.uuid4().hex[:8]}"
    project_b = f"project-b-{uuid.uuid4().hex[:8]}"

    create_project(project_a, "Project A")
    create_project(project_b, "Project B")

    review_id, article_id = _create_review_and_article(project_a)

    try:
        _select_project(dashboard_client, project_b)

        response = dashboard_client.post(
            "/api/systematic-review/full-text-retrieval",
            json={
                "review_id": review_id,
                "article_id": article_id,
                "status": "sought",
            },
        )

        assert response.status_code == 404

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT full_text_retrieval_status
                FROM review_articles
                WHERE id = %s
                """,
                (article_id,),
            )
            assert cur.fetchone()[0] == "not_sought"

    finally:
        _cleanup_project(project_a)
        _cleanup_project(project_b)


def test_project_b_cannot_validate_extraction_from_project_a(
    dashboard_client,
):
    project_a = f"project-a-{uuid.uuid4().hex[:8]}"
    project_b = f"project-b-{uuid.uuid4().hex[:8]}"

    create_project(project_a, "Project A")
    create_project(project_b, "Project B")

    review_id, article_id = _create_review_and_article(project_a)
    extraction_id = _create_extraction(review_id, article_id)

    try:
        _select_project(dashboard_client, project_b)

        response = dashboard_client.post(
            "/api/systematic-review/human-data-extraction",
            json={
                "extraction_id": extraction_id,
                "validation_status": "accepted",
                "reviewer_id": "reviewer_1",
            },
        )

        assert response.status_code == 404

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT validation_status
                FROM review_extractions
                WHERE id = %s
                """,
                (extraction_id,),
            )
            assert cur.fetchone()[0] == "pending"

    finally:
        _cleanup_project(project_a)
        _cleanup_project(project_b)


def test_human_screening_rejects_article_review_mismatch():
    from workers.plugins.human_screening import _resolve_article

    project_id = f"project-{uuid.uuid4().hex[:8]}"
    create_project(project_id, "Worker isolation test")

    review_a, article_a = _create_review_and_article(project_id)
    review_b, _article_b = _create_review_and_article(project_id)

    try:
        with get_conn() as conn, conn.cursor() as cur:
            try:
                _resolve_article(
                    cur,
                    article_id=article_a,
                    review_id=review_b,
                    project_id=project_id,
                )
            except ValueError as exc:
                assert "Artículo no encontrado" in str(exc)
            else:
                raise AssertionError(
                    "El worker aceptó un article_id de otra revisión"
                )

    finally:
        _cleanup_project(project_id)
