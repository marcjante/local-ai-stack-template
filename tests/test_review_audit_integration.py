import uuid

from db.db import create_project, get_conn, get_review_audit_trail


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
                "Audit integration test",
                "systematic_review",
                "Does audit integration work?",
                "Relevant studies",
                "Irrelevant studies",
                "screening",
            ),
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
                article_id,
                review_id,
                "Audit integration article",
                "Test abstract",
            ),
        )

    return review_id, article_id


def _select_project(client, project_id):
    with client.session_transaction() as sess:
        sess["project_id"] = project_id


def _cleanup(project_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM systematic_reviews WHERE project_id = %s",
            (project_id,),
        )
        cur.execute(
            "DELETE FROM projects WHERE id = %s",
            (project_id,),
        )


def test_human_screening_creates_review_audit_event(dashboard_client):
    project_id = f"audit-project-{uuid.uuid4().hex[:8]}"
    create_project(project_id, "Audit integration project")
    review_id, article_id = _create_review_and_article(project_id)

    try:
        _select_project(dashboard_client, project_id)

        response = dashboard_client.post(
            "/api/systematic-review/human-decision",
            json={
                "review_id": review_id,
                "article_id": article_id,
                "reviewer_id": "reviewer_1",
                "stage": "title_abstract",
                "decision": "include",
                "notes": "Audit integration test",
            },
        )

        assert response.status_code == 200, response.get_data(as_text=True)

        trail = get_review_audit_trail(
            review_id,
            project_id=project_id,
            article_id=article_id,
        )

        assert len(trail) == 1

        event = trail[0]

        assert event["action"] == "human_screening_decision"
        assert event["actor_type"] == "human"
        assert event["actor_id"] == "reviewer_1"
        assert event["stage"] == "title_abstract"
        assert event["details"]["decision"] == "include"

    finally:
        _cleanup(project_id)


def test_conflict_resolution_creates_review_audit_event(dashboard_client):
    project_id = f"audit-project-{uuid.uuid4().hex[:8]}"
    create_project(project_id, "Audit integration project")
    review_id, article_id = _create_review_and_article(project_id)

    try:
        _select_project(dashboard_client, project_id)

        first = dashboard_client.post(
            "/api/systematic-review/human-decision",
            json={
                "review_id": review_id,
                "article_id": article_id,
                "reviewer_id": "reviewer_1",
                "stage": "title_abstract",
                "decision": "include",
            },
        )
        assert first.status_code == 200

        second = dashboard_client.post(
            "/api/systematic-review/human-decision",
            json={
                "review_id": review_id,
                "article_id": article_id,
                "reviewer_id": "reviewer_2",
                "stage": "title_abstract",
                "decision": "exclude",
                "exclusion_reason_code": "NOT_RELEVANT",
                "exclusion_reason": "Not relevant",
            },
        )
        assert second.status_code == 200

        resolved = dashboard_client.post(
            "/api/systematic-review/resolve-conflict",
            json={
                "review_id": review_id,
                "article_id": article_id,
                "stage": "title_abstract",
                "resolution": "include",
                "resolved_by": "adjudicator",
                "resolution_notes": "Resolved in favour of inclusion",
            },
        )

        assert resolved.status_code == 200, resolved.get_data(as_text=True)

        trail = get_review_audit_trail(
            review_id,
            project_id=project_id,
            article_id=article_id,
        )

        actions = [event["action"] for event in trail]

        assert actions.count("human_screening_decision") == 2
        assert "screening_conflict_resolved" in actions

        conflict_event = next(
            event
            for event in trail
            if event["action"] == "screening_conflict_resolved"
        )

        assert conflict_event["actor_id"] == "adjudicator"
        assert conflict_event["details"]["resolution"] == "include"
        assert conflict_event["after_state"]["conflict_status"] == "resolved"

    finally:
        _cleanup(project_id)



def test_full_text_retrieval_creates_review_audit_event(dashboard_client):
    project_id = f"audit-project-{uuid.uuid4().hex[:8]}"
    create_project(project_id, "Audit full text project")
    review_id, article_id = _create_review_and_article(project_id)

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE review_articles
                SET
                    title_abstract_status = 'include',
                    human_decision = 'include',
                    screening_status = 'reviewed',
                    screening_stage = 'title_abstract',
                    full_text_status = 'pending'
                WHERE id = %s
                  AND review_id = %s
                """,
                (
                    article_id,
                    review_id,
                ),
            )

        _select_project(dashboard_client, project_id)

        response = dashboard_client.post(
            "/api/systematic-review/full-text-retrieval",
            json={
                "review_id": review_id,
                "article_id": article_id,
                "status": "sought",
            },
        )

        assert response.status_code == 200, response.get_data(as_text=True)

        trail = get_review_audit_trail(
            review_id,
            project_id=project_id,
            article_id=article_id,
        )

        event = next(
            event
            for event in trail
            if event["action"] == "full_text_retrieval_status_changed"
        )

        assert event["stage"] == "full_text"
        assert event["before_state"]["full_text_retrieval_status"] == "not_sought"
        assert event["after_state"]["full_text_retrieval_status"] == "sought"
        assert event["after_state"]["full_text_available"] is False

    finally:
        _cleanup(project_id)


def test_human_extraction_validation_creates_review_audit_event(
    dashboard_client,
):
    project_id = f"audit-project-{uuid.uuid4().hex[:8]}"
    create_project(project_id, "Audit extraction project")
    review_id, article_id = _create_review_and_article(project_id)

    field_id = f"field-{uuid.uuid4().hex}"
    extraction_id = f"extraction-{uuid.uuid4().hex}"

    try:
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
                VALUES (%s, %s, %s, %s, 'text', FALSE, 1)
                """,
                (
                    field_id,
                    review_id,
                    "sample_size",
                    "Sample size",
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
                    '"120"',
                ),
            )

        _select_project(dashboard_client, project_id)

        response = dashboard_client.post(
            "/api/systematic-review/human-data-extraction",
            json={
                "extraction_id": extraction_id,
                "validation_status": "accepted",
                "reviewer_id": "reviewer_1",
                "reviewer_notes": "Validated for audit test",
            },
        )

        assert response.status_code == 200, response.get_data(as_text=True)

        trail = get_review_audit_trail(
            review_id,
            project_id=project_id,
            article_id=article_id,
        )

        event = next(
            event
            for event in trail
            if event["action"] == "human_extraction_validation"
        )

        assert event["extraction_id"] == extraction_id
        assert event["actor_type"] == "human"
        assert event["actor_id"] == "reviewer_1"
        assert event["stage"] == "data_extraction"

        assert event["before_state"]["validation_status"] == "pending"
        assert event["after_state"]["validation_status"] == "accepted"
        assert event["details"]["field_key"] == "sample_size"
        assert event["details"]["agreement_with_ai"] is True

    finally:
        _cleanup(project_id)
