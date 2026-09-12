import uuid

import pytest

from workers.plugins.data_extraction import _load_extraction_context
from db.db import get_conn


@pytest.fixture
def review_with_extraction_field():
    review_id = str(uuid.uuid4())
    field_id = str(uuid.uuid4())

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name)
            VALUES (%s, %s)
            RETURNING id
            """,
            (
                str(uuid.uuid4()),
                "Data extraction test project",
            ),
        )
        project_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO systematic_reviews (
                id,
                project_id,
                title
            )
            VALUES (%s, %s, %s)
            """,
            (
                review_id,
                project_id,
                "Data extraction test review",
            ),
        )

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
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                field_id,
                review_id,
                "sample_size",
                "Sample size",
                "integer",
                False,
                1,
            ),
        )

    yield review_id

    with get_conn() as conn, conn.cursor() as cur:
        # Recuperamos el proyecto antes de eliminar la revisión.
        cur.execute(
            """
            SELECT project_id
            FROM systematic_reviews
            WHERE id = %s
            """,
            (review_id,),
        )
        row = cur.fetchone()
        project_id = row[0] if row else None

        # Algunos tests enlazan un documento de texto completo al artículo.
        # Rompemos primero ese enlace para que la limpieza respete las FK.
        cur.execute(
            """
            UPDATE review_articles
            SET full_text_document_id = NULL
            WHERE review_id = %s
            """,
            (review_id,),
        )

        if project_id:
            cur.execute(
                """
                DELETE FROM documents
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


def _insert_article(
    review_id,
    *,
    final_decision,
    screening_status,
    retrieval_status,
):
    article_id = str(uuid.uuid4())

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO review_articles (
                id,
                review_id,
                title,
                abstract,
                screening_status,
                final_decision,
                full_text_retrieval_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                article_id,
                review_id,
                "Test article",
                "This is a test abstract.",
                screening_status,
                final_decision,
                retrieval_status,
            ),
        )

    return article_id


def test_data_extraction_only_selects_final_included_retrieved_articles(
    review_with_extraction_field,
):
    review_id = review_with_extraction_field

    eligible_id = _insert_article(
        review_id,
        final_decision="include",
        screening_status="reviewed",
        retrieval_status="retrieved",
    )

    _insert_article(
        review_id,
        final_decision="include",
        screening_status="reviewed",
        retrieval_status="not_retrieved",
    )

    _insert_article(
        review_id,
        final_decision="exclude",
        screening_status="reviewed",
        retrieval_status="retrieved",
    )

    _insert_article(
        review_id,
        final_decision=None,
        screening_status="reviewed",
        retrieval_status="retrieved",
    )

    context = _load_extraction_context(review_id)

    assert len(context["articles"]) == 1
    assert context["articles"][0]["id"] == eligible_id
    assert context["articles"][0]["final_decision"] == "include"
    assert (
        context["articles"][0]["full_text_retrieval_status"]
        == "retrieved"
    )


def test_extraction_context_includes_project_and_full_text_document(
    review_with_extraction_field,
):
    review_id = review_with_extraction_field
    article_id = _insert_article(
        review_id,
        final_decision="include",
        screening_status="reviewed",
        retrieval_status="retrieved",
    )

    document_id = f"doc-{uuid.uuid4().hex}"

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT project_id
            FROM systematic_reviews
            WHERE id = %s
            """,
            (review_id,),
        )
        project_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO documents (
                doc_id,
                project_id,
                filename,
                content_type,
                raw_text,
                n_chunks
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                document_id,
                project_id,
                "test-full-text.txt",
                "text/plain",
                "Test full text document.",
                0,
            ),
        )

        cur.execute(
            """
            UPDATE review_articles
            SET full_text_document_id = %s
            WHERE id = %s
            """,
            (
                document_id,
                article_id,
            ),
        )

    context = _load_extraction_context(review_id)

    article = context["articles"][0]

    assert context["review"]["project_id"]
    assert article["project_id"] == context["review"]["project_id"]
    assert article["full_text_document_id"] == document_id


def test_prepare_source_prefers_full_text_rag(monkeypatch):
    from workers.plugins import data_extraction

    article = {
        "id": "article-1",
        "title": "Randomized tuberculosis treatment study",
        "abstract": "Abstract fallback text.",
        "full_text_document_id": "doc-1",
        "project_id": "project-1",
    }

    field = {
        "field_key": "sample_size",
        "label": "Sample size",
        "description": "Number of participants included in the study",
    }

    received = {}

    def fake_retrieve(
        query,
        top_k=20,
        doc_id=None,
        project_id=None,
    ):
        received["query"] = query
        received["top_k"] = top_k
        received["doc_id"] = doc_id
        received["project_id"] = project_id

        return [
            {
                "chunk_id": "chunk-1",
                "doc_id": "doc-1",
                "position": 4,
                "text": "A total of 120 participants were enrolled.",
                "doc_version": "v1",
                "score": 0.91,
            },
            {
                "chunk_id": "chunk-2",
                "doc_id": "doc-1",
                "position": 9,
                "text": "Participants were randomly allocated.",
                "doc_version": "v1",
                "score": 0.75,
            },
        ]

    monkeypatch.setattr(
        data_extraction,
        "retrieve",
        fake_retrieve,
    )

    source = data_extraction._prepare_source(
        article,
        field,
    )

    assert source["source_type"] == "full_text"
    assert source["document_id"] == "doc-1"

    assert received["doc_id"] == "doc-1"
    assert received["project_id"] == "project-1"

    assert (
        "A total of 120 participants were enrolled."
        in source["source_text"]
    )

    location = __import__("json").loads(
        source["source_location"]
    )

    assert location["doc_id"] == "doc-1"
    assert location["chunks"][0]["chunk_id"]


def test_prepare_source_falls_back_to_abstract(monkeypatch):
    from workers.plugins import data_extraction

    article = {
        "id": "article-1",
        "title": "Test article",
        "abstract": "This abstract contains the sample size.",
        "full_text_document_id": "doc-1",
        "project_id": "project-1",
    }

    field = {
        "field_key": "sample_size",
        "label": "Sample size",
        "description": None,
    }

    monkeypatch.setattr(
        data_extraction,
        "retrieve",
        lambda *args, **kwargs: [],
    )

    source = data_extraction._prepare_source(
        article,
        field,
    )

    assert source["source_type"] == "abstract"
    assert source["source_location"] == "abstract"
    assert (
        source["source_text"]
        == "This abstract contains the sample size."
    )


def test_source_quote_must_exist_in_retrieved_evidence():
    from workers.plugins.data_extraction import (
        _validate_source_quote,
    )

    evidence = (
        "A total of 120 participants were enrolled "
        "between January and June."
    )

    assert (
        _validate_source_quote(
            "A total of 120 participants were enrolled",
            evidence,
        )
        == "A total of 120 participants were enrolled"
    )

    assert (
        _validate_source_quote(
            "A total of 999 participants were enrolled",
            evidence,
        )
        is None
    )
