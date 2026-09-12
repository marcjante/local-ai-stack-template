import uuid

from db.db import (
    create_project,
    get_conn,
    get_review_audit_trail,
    log_review_audit,
)


def test_review_audit_log_roundtrip():
    project_id = f"audit-project-{uuid.uuid4().hex[:8]}"
    review_id = f"audit-review-{uuid.uuid4().hex}"
    article_id = f"audit-article-{uuid.uuid4().hex}"

    create_project(project_id, "Audit test project")

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO systematic_reviews (
                    id,
                    project_id,
                    title,
                    status
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    review_id,
                    project_id,
                    "Audit test review",
                    "screening",
                ),
            )

            cur.execute(
                """
                INSERT INTO review_articles (
                    id,
                    review_id,
                    title
                )
                VALUES (%s, %s, %s)
                """,
                (
                    article_id,
                    review_id,
                    "Audit test article",
                ),
            )

        audit_id = log_review_audit(
            project_id=project_id,
            review_id=review_id,
            article_id=article_id,
            action="human_screening_decision",
            actor_type="human",
            actor_id="reviewer_1",
            stage="title_abstract",
            before_state={
                "status": "pending",
            },
            after_state={
                "status": "include",
            },
            details={
                "decision": "include",
                "notes": "Test audit event",
            },
        )

        assert audit_id is not None

        trail = get_review_audit_trail(
            review_id,
            project_id=project_id,
        )

        assert len(trail) == 1

        event = trail[0]

        assert event["id"] == audit_id
        assert event["project_id"] == project_id
        assert event["review_id"] == review_id
        assert event["article_id"] == article_id
        assert event["action"] == "human_screening_decision"
        assert event["actor_type"] == "human"
        assert event["actor_id"] == "reviewer_1"
        assert event["stage"] == "title_abstract"

        assert event["before_state"] == {
            "status": "pending",
        }

        assert event["after_state"] == {
            "status": "include",
        }

        assert event["details"]["decision"] == "include"
        assert event["details"]["notes"] == "Test audit event"

    finally:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM systematic_reviews
                WHERE id = %s
                """,
                (review_id,),
            )

            cur.execute(
                """
                DELETE FROM projects
                WHERE id = %s
                """,
                (project_id,),
            )
