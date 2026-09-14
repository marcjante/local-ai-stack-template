import logging
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from db.db import get_conn, log_review_audit, set_status

QUEUE_NAME = "resolve_screening_conflict"
QUEUE_TIMEOUT = 120

logger = logging.getLogger(__name__)

VALID_DECISIONS = {"include", "exclude", "uncertain"}
VALID_STAGES = {"title_abstract", "full_text"}


def handle(task_id, payload):
    set_status(task_id, "running")

    try:
        article_id = payload.get("article_id")
        review_id = payload.get("review_id")
        project_id = payload.get("project_id")
        stage = (payload.get("stage") or "").strip().lower()
        resolution = (payload.get("resolution") or "").strip().lower()
        resolved_by = (payload.get("resolved_by") or "").strip()
        resolution_notes = payload.get("resolution_notes")
        exclusion_reason = payload.get("exclusion_reason")
        exclusion_reason_code = payload.get("exclusion_reason_code")

        if not article_id:
            raise ValueError("article_id es obligatorio")

        if not review_id:
            raise ValueError("review_id es obligatorio")

        if not project_id:
            raise ValueError("project_id es obligatorio")

        if stage not in VALID_STAGES:
            raise ValueError("stage debe ser title_abstract o full_text")

        if resolution not in VALID_DECISIONS:
            raise ValueError(
                "resolution debe ser include, exclude o uncertain"
            )

        if not resolved_by:
            raise ValueError("resolved_by es obligatorio")

        if resolution == "exclude" and not (
            exclusion_reason or exclusion_reason_code
        ):
            raise ValueError(
                "Cuando resolution=exclude debes indicar exclusion_reason "
                "o exclusion_reason_code"
            )

        if resolution != "exclude":
            exclusion_reason = None
            exclusion_reason_code = None

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        ra.id,
                        sr.project_id,
                        ra.title_abstract_status,
                        ra.full_text_status,
                        ra.human_decision,
                        ra.final_decision,
                        ra.screening_status,
                        ra.screening_stage
                    FROM review_articles ra
                    JOIN systematic_reviews sr
                      ON sr.id = ra.review_id
                    WHERE ra.id = %s
                      AND ra.review_id = %s
                      AND sr.project_id = %s
                    """,
                    (article_id, review_id, project_id),
                )

                article_before = cur.fetchone()

                if not article_before:
                    raise ValueError(
                        "El artículo no existe o no pertenece a la revisión"
                    )

                (
                    _db_article_id,
                    db_project_id,
                    before_title_abstract_status,
                    before_full_text_status,
                    before_human_decision,
                    before_final_decision,
                    before_screening_status,
                    before_screening_stage,
                ) = article_before

                cur.execute(
                    """
                    SELECT id, status
                    FROM review_screening_conflicts
                    WHERE article_id = %s
                      AND review_id = %s
                      AND stage = %s
                    """,
                    (article_id, review_id, stage),
                )

                conflict = cur.fetchone()

                if not conflict:
                    raise ValueError(
                        "No existe un conflicto para este artículo y fase"
                    )

                conflict_id, conflict_status = conflict

                if conflict_status == "resolved":
                    raise ValueError("El conflicto ya estaba resuelto")

                cur.execute(
                    """
                    UPDATE review_screening_conflicts
                    SET
                        status = 'resolved',
                        resolution = %s,
                        resolved_by = %s,
                        resolution_notes = %s,
                        resolved_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        resolution,
                        resolved_by,
                        resolution_notes,
                        conflict_id,
                    ),
                )

                if stage == "title_abstract":
                    next_full_text_status = (
                        "pending"
                        if resolution in {"include", "uncertain"}
                        else "not_started"
                    )

                    cur.execute(
                        """
                        UPDATE review_articles
                        SET
                            title_abstract_status = %s,
                            full_text_status = %s,
                            human_decision = %s,
                            exclusion_reason_code = %s,
                            exclusion_reason = %s,
                            screening_status = 'reviewed',
                            screening_stage = 'title_abstract',
                            updated_at = NOW()
                        WHERE id = %s
                          AND review_id = %s
                        """,
                        (
                            resolution,
                            next_full_text_status,
                            resolution,
                            exclusion_reason_code,
                            exclusion_reason,
                            article_id,
                            review_id,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE review_articles
                        SET
                            full_text_status = %s,
                            final_decision = %s,
                            human_decision = %s,
                            exclusion_reason_code = %s,
                            exclusion_reason = %s,
                            screening_status = 'reviewed',
                            screening_stage = 'full_text',
                            updated_at = NOW()
                        WHERE id = %s
                          AND review_id = %s
                        """,
                        (
                            resolution,
                            resolution,
                            resolution,
                            exclusion_reason_code,
                            exclusion_reason,
                            article_id,
                            review_id,
                        ),
                    )

                cur.execute(
                    """
                    SELECT
                        title_abstract_status,
                        full_text_status,
                        human_decision,
                        final_decision,
                        screening_status,
                        screening_stage
                    FROM review_articles
                    WHERE id = %s
                    """,
                    (article_id,),
                )
                article_after = cur.fetchone()

                log_review_audit(
                    project_id=project_id,
                    review_id=review_id,
                    article_id=article_id,
                    action="screening_conflict_resolved",
                    actor_type="human",
                    actor_id=resolved_by,
                    stage=stage,
                    before_state={
                        "title_abstract_status": before_title_abstract_status,
                        "full_text_status": before_full_text_status,
                        "human_decision": before_human_decision,
                        "final_decision": before_final_decision,
                        "screening_status": before_screening_status,
                        "screening_stage": before_screening_stage,
                        "conflict_status": conflict_status,
                    },
                    after_state={
                        "title_abstract_status": article_after[0],
                        "full_text_status": article_after[1],
                        "human_decision": article_after[2],
                        "final_decision": article_after[3],
                        "screening_status": article_after[4],
                        "screening_stage": article_after[5],
                        "conflict_status": "resolved",
                    },
                    details={
                        "resolution": resolution,
                        "resolution_notes": resolution_notes,
                        "exclusion_reason": exclusion_reason,
                        "exclusion_reason_code": exclusion_reason_code,
                        "conflict_id": conflict_id,
                    },
                    conn=conn,
                )

        result = {
            "review_id": review_id,
            "article_id": article_id,
            "stage": stage,
            "resolution": resolution,
            "resolved_by": resolved_by,
            "status": "resolved",
            "exclusion_reason": exclusion_reason,
            "exclusion_reason_code": exclusion_reason_code,
        }

        set_status(task_id, "completed", result=result)

        logger.info(
            "task_id=%s — Conflicto resuelto: article=%s stage=%s resolution=%s",
            task_id,
            article_id,
            stage,
            resolution,
        )

        return result

    except Exception as exc:
        logger.exception(
            "task_id=%s — Error resolviendo conflicto de screening",
            task_id,
        )
        set_status(task_id, "failed", error=str(exc))
        raise
