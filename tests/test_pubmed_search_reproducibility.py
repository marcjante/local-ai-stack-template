import uuid

import pytest

from db.db import get_conn
from workers.plugins.pubmed_search import _save_review_search


def _project_id_for_review(review_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT project_id
            FROM systematic_reviews
            WHERE id = %s
            """,
            (review_id,),
        )
        row = cur.fetchone()

    if not row:
        raise AssertionError(
            f"No existe la revisión de test: {review_id}"
        )

    return row[0]




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
                status
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                review_id,
                project_id,
                "PubMed reproducibility test",
                "systematic_review",
                "draft",
            ),
        )

    return review_id


def _insert_strategy(
    review_id,
    query,
    version=1,
    human_confirmed=True,
):
    strategy_id = f"strategy-{uuid.uuid4().hex}"

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO review_search_strategies (
                id,
                review_id,
                database_name,
                version,
                query,
                is_valid,
                accepted_by_database,
                human_confirmed,
                confirmed_at
            )
            VALUES (
                %s,
                %s,
                'PubMed',
                %s,
                %s,
                TRUE,
                TRUE,
                %s,
                CASE
                    WHEN %s THEN CURRENT_TIMESTAMP
                    ELSE NULL
                END
            )
            """,
            (
                strategy_id,
                review_id,
                version,
                query,
                human_confirmed,
                human_confirmed,
            ),
        )

    return strategy_id


def test_direct_pubmed_search_creates_reproducible_strategy(
    project_id,
):
    review_id = _insert_review(project_id)
    query = "tuberculosis digital health adherence"

    result = _save_review_search(
        review_id=review_id,
        project_id=project_id,
        query=query,
        total_found=249,
        articles=[],
        strategy_id=None,
    )

    assert result["strategy_id"]
    assert result["search_id"]
    assert result["imported"] == 0

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                database_name,
                version,
                query,
                is_valid,
                accepted_by_database,
                total_found,
                provider,
                human_confirmed,
                confirmed_at
            FROM review_search_strategies
            WHERE id = %s
            """,
            (result["strategy_id"],),
        )
        strategy = cur.fetchone()

    assert strategy is not None
    assert strategy[0] == "PubMed"
    assert strategy[1] == 1
    assert strategy[2] == query
    assert strategy[3] is True
    assert strategy[4] is True
    assert strategy[5] == 249
    assert strategy[6] == "direct_pubmed_execution"
    assert strategy[7] is True
    assert strategy[8] is not None


def test_direct_pubmed_search_links_execution_to_strategy(
    project_id,
):
    review_id = _insert_review(project_id)

    result = _save_review_search(
        review_id=review_id,
        project_id=project_id,
        query="tuberculosis adherence",
        total_found=100,
        articles=[],
        strategy_id=None,
    )

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                review_id,
                database_name,
                query,
                total_found,
                strategy_id
            FROM review_searches
            WHERE id = %s
            """,
            (result["search_id"],),
        )
        search = cur.fetchone()

    assert search is not None
    assert search[0] == review_id
    assert search[1] == "PubMed"
    assert search[2] == "tuberculosis adherence"
    assert search[3] == 100
    assert search[4] == result["strategy_id"]


def test_direct_pubmed_search_increments_strategy_version(
    project_id,
):
    review_id = _insert_review(project_id)

    _insert_strategy(
        review_id,
        query="first query",
        version=1,
    )

    _insert_strategy(
        review_id,
        query="second query",
        version=2,
    )

    result = _save_review_search(
        review_id=review_id,
        project_id=project_id,
        query="third query",
        total_found=42,
        articles=[],
        strategy_id=None,
    )

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT version, query
            FROM review_search_strategies
            WHERE id = %s
            """,
            (result["strategy_id"],),
        )
        row = cur.fetchone()

    assert row == (3, "third query")


def test_confirmed_strategy_is_reused_without_duplicate(
    project_id,
):
    review_id = _insert_review(project_id)
    query = "tuberculosis AND digital health"

    strategy_id = _insert_strategy(
        review_id,
        query=query,
        version=1,
        human_confirmed=True,
    )

    result = _save_review_search(
        review_id=review_id,
        project_id=project_id,
        query=query,
        total_found=75,
        articles=[],
        strategy_id=strategy_id,
    )

    assert result["strategy_id"] == strategy_id

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM review_search_strategies
            WHERE review_id = %s
            """,
            (review_id,),
        )
        strategy_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT strategy_id
            FROM review_searches
            WHERE id = %s
            """,
            (result["search_id"],),
        )
        linked_strategy_id = cur.fetchone()[0]

    assert strategy_count == 1
    assert linked_strategy_id == strategy_id


def test_unconfirmed_strategy_cannot_be_executed(
    project_id,
):
    review_id = _insert_review(project_id)
    query = "unconfirmed tuberculosis query"

    strategy_id = _insert_strategy(
        review_id,
        query=query,
        human_confirmed=False,
    )

    with pytest.raises(
        ValueError,
        match="confirmación humana",
    ):
        _save_review_search(
            review_id=review_id,
            project_id=project_id,
            query=query,
            total_found=10,
            articles=[],
            strategy_id=strategy_id,
        )

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM review_searches
            WHERE review_id = %s
            """,
            (review_id,),
        )
        assert cur.fetchone()[0] == 0
