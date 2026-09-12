import io
import uuid

from db.db import get_conn, get_review_audit_trail


def _create_review_with_article(project_id, *, full_text_status="pending", is_duplicate=False):
    review_id = f"review-{uuid.uuid4().hex}"
    article_id = f"article-{uuid.uuid4().hex}"

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO systematic_reviews (
                id,
                project_id,
                title,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, NOW(), NOW())
            """,
            (
                review_id,
                project_id,
                "Full text upload test review",
            ),
        )

        cur.execute(
            """
            INSERT INTO review_articles (
                id,
                review_id,
                title,
                screening_status,
                title_abstract_status,
                full_text_status,
                full_text_available,
                full_text_retrieval_status,
                is_duplicate
            )
            VALUES (
                %s,
                %s,
                %s,
                'reviewed',
                'include',
                %s,
                FALSE,
                'not_sought',
                %s
            )
            """,
            (
                article_id,
                review_id,
                "Test article",
                full_text_status,
                is_duplicate,
            ),
        )

    return review_id, article_id


def _cleanup_review(review_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT full_text_document_id
            FROM review_articles
            WHERE review_id = %s
              AND full_text_document_id IS NOT NULL
            """,
            (review_id,),
        )
        doc_ids = [row[0] for row in cur.fetchall()]

        cur.execute(
            "DELETE FROM systematic_reviews WHERE id = %s",
            (review_id,),
        )

        for doc_id in doc_ids:
            cur.execute(
                "DELETE FROM rag_chunks WHERE doc_id = %s",
                (doc_id,),
            )
            cur.execute(
                "DELETE FROM documents WHERE doc_id = %s",
                (doc_id,),
            )


def test_full_text_upload_success(dashboard_client, project_id):
    review_id, article_id = _create_review_with_article(project_id)

    try:
        response = dashboard_client.post(
            "/api/systematic-review/full-text-upload",
            data={
                "review_id": review_id,
                "article_id": article_id,
                "file": (
                    io.BytesIO(
                        b"""
                        Randomized controlled trial.

                        Methods:
                        Participants received intervention or control.

                        Results:
                        The intervention group improved significantly.
                        """
                    ),
                    "article.txt",
                ),
            },
            content_type="multipart/form-data",
        )

        assert response.status_code == 201
        payload = response.get_json()

        assert payload["ok"] is True
        assert payload["article_id"] == article_id
        assert payload["document_id"]
        assert payload["n_chunks"] > 0
        assert payload["full_text_retrieval_status"] == "retrieved"
        assert payload["full_text_available"] is True

        audit_trail = get_review_audit_trail(
            review_id,
            project_id=project_id,
            article_id=article_id,
        )

        upload_events = [
            event
            for event in audit_trail
            if event["action"] == "full_text_uploaded"
        ]

        assert len(upload_events) == 1

        upload_event = upload_events[0]

        assert upload_event["after_state"]["full_text_document_id"] == payload["document_id"]
        assert upload_event["after_state"]["full_text_retrieval_status"] == "retrieved"
        assert upload_event["after_state"]["full_text_available"] is True
        assert upload_event["details"]["filename"] == "article.txt"
        assert upload_event["details"]["n_chunks"] > 0

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    full_text_document_id,
                    full_text_retrieval_status,
                    full_text_available
                FROM review_articles
                WHERE id = %s
                """,
                (article_id,),
            )
            row = cur.fetchone()

            assert row[0] == payload["document_id"]
            assert row[1] == "retrieved"
            assert row[2] is True

            cur.execute(
                """
                SELECT project_id, filename, n_chunks
                FROM documents
                WHERE doc_id = %s
                """,
                (payload["document_id"],),
            )
            document = cur.fetchone()

            assert document[0] == project_id
            assert document[1] == "article.txt"
            assert document[2] > 0

    finally:
        _cleanup_review(review_id)


def test_full_text_upload_rejects_unknown_article(dashboard_client):
    response = dashboard_client.post(
        "/api/systematic-review/full-text-upload",
        data={
            "review_id": "missing-review",
            "article_id": "missing-article",
            "file": (
                io.BytesIO(b"Example full text"),
                "article.txt",
            ),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 404


def test_full_text_upload_rejects_duplicate(dashboard_client, project_id):
    review_id, article_id = _create_review_with_article(
        project_id,
        is_duplicate=True,
    )

    try:
        response = dashboard_client.post(
            "/api/systematic-review/full-text-upload",
            data={
                "review_id": review_id,
                "article_id": article_id,
                "file": (
                    io.BytesIO(b"Example full text"),
                    "article.txt",
                ),
            },
            content_type="multipart/form-data",
        )

        assert response.status_code == 400
        assert "duplicado" in response.get_json()["error"].lower()

    finally:
        _cleanup_review(review_id)


def test_full_text_upload_rejects_article_before_full_text_stage(
    dashboard_client,
    project_id,
):
    review_id, article_id = _create_review_with_article(
        project_id,
        full_text_status="not_started",
    )

    try:
        response = dashboard_client.post(
            "/api/systematic-review/full-text-upload",
            data={
                "review_id": review_id,
                "article_id": article_id,
                "file": (
                    io.BytesIO(b"Example full text"),
                    "article.txt",
                ),
            },
            content_type="multipart/form-data",
        )

        assert response.status_code == 409

    finally:
        _cleanup_review(review_id)


def test_full_text_upload_replaces_previous_document(
    dashboard_client,
    project_id,
):
    review_id, article_id = _create_review_with_article(project_id)

    try:
        first = dashboard_client.post(
            "/api/systematic-review/full-text-upload",
            data={
                "review_id": review_id,
                "article_id": article_id,
                "file": (
                    io.BytesIO(b"First full text version with enough content."),
                    "first.txt",
                ),
            },
            content_type="multipart/form-data",
        )

        assert first.status_code == 201
        first_doc_id = first.get_json()["document_id"]

        second = dashboard_client.post(
            "/api/systematic-review/full-text-upload",
            data={
                "review_id": review_id,
                "article_id": article_id,
                "file": (
                    io.BytesIO(
                        b"Second full text version with updated content."
                    ),
                    "second.txt",
                ),
            },
            content_type="multipart/form-data",
        )

        assert second.status_code == 201
        second_doc_id = second.get_json()["document_id"]

        assert second_doc_id != first_doc_id

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT full_text_document_id
                FROM review_articles
                WHERE id = %s
                """,
                (article_id,),
            )
            assert cur.fetchone()[0] == second_doc_id

            cur.execute(
                "SELECT COUNT(*) FROM documents WHERE doc_id = %s",
                (first_doc_id,),
            )
            assert cur.fetchone()[0] == 0

            cur.execute(
                "SELECT COUNT(*) FROM documents WHERE doc_id = %s",
                (second_doc_id,),
            )
            assert cur.fetchone()[0] == 1

    finally:
        _cleanup_review(review_id)
