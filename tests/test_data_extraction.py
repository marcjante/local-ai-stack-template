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
        cur.execute(
            """
            DELETE FROM projects
            WHERE id IN (
                SELECT project_id
                FROM systematic_reviews
                WHERE id = %s
            )
            """,
            (review_id,),
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
