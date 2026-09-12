import logging
import os
import sys

from psycopg2.extras import Json

sys.path.append(
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../..")
    )
)

from db.db import get_conn, log_audit, log_review_audit, set_status

QUEUE_NAME = "human_data_extraction"
QUEUE_TIMEOUT = 120

logger = logging.getLogger(__name__)

VALID_STATUSES = {
    "accepted",
    "edited",
    "rejected",
}


def handle(task_id, payload):
    set_status(task_id, "running")

    try:
        extraction_id = payload.get("extraction_id")
        reviewer_id = (
            payload.get("reviewer_id")
            or ""
        ).strip() or None

        reviewer_notes = (
            payload.get("reviewer_notes")
            or ""
        ).strip() or None

        validation_status = (
            payload.get("validation_status")
            or ""
        ).strip().lower()

        human_value_provided = "human_value" in payload
        human_value = payload.get("human_value")

        if not extraction_id:
            raise ValueError(
                "extraction_id es obligatorio"
            )

        if validation_status not in VALID_STATUSES:
            raise ValueError(
                "validation_status debe ser "
                "accepted, edited o rejected"
            )

        if not reviewer_id:
            raise ValueError(
                "reviewer_id es obligatorio"
            )

        if (
            validation_status == "edited"
            and not human_value_provided
        ):
            raise ValueError(
                "human_value es obligatorio "
                "cuando validation_status=edited"
            )

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        re.id,
                        re.review_id,
                        re.article_id,
                        re.field_id,
                        re.ai_value,
                        re.validation_status,
                        ra.pmid,
                        ra.title,
                        ref.field_key,
                        ref.label,
                        sr.project_id
                    FROM review_extractions re
                    JOIN review_articles ra
                      ON ra.id = re.article_id
                    JOIN review_extraction_fields ref
                      ON ref.id = re.field_id
                    JOIN systematic_reviews sr
                      ON sr.id = re.review_id
                    WHERE re.id = %s
                    FOR UPDATE
                    """,
                    (extraction_id,),
                )

                row = cur.fetchone()

                if not row:
                    raise ValueError(
                        "Extracción no encontrada"
                    )

                (
                    db_extraction_id,
                    review_id,
                    article_id,
                    field_id,
                    ai_value,
                    previous_status,
                    pmid,
                    title,
                    field_key,
                    field_label,
                    project_id,
                ) = row

                if previous_status != "pending":
                    raise ValueError(
                        "La extracción ya fue revisada "
                        f"y tiene estado '{previous_status}'"
                    )

                if validation_status == "accepted":
                    final_human_value = ai_value

                elif validation_status == "edited":
                    final_human_value = human_value

                else:
                    final_human_value = None

                cur.execute(
                    """
                    UPDATE review_extractions
                    SET
                        human_value = %s,
                        validation_status = %s,
                        reviewer_id = %s,
                        reviewer_notes = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        Json(final_human_value),
                        validation_status,
                        reviewer_id,
                        reviewer_notes,
                        db_extraction_id,
                    ),
                )

        result = {
            "extraction_id": db_extraction_id,
            "review_id": review_id,
            "article_id": article_id,
            "pmid": pmid,
            "title": title,
            "field_id": field_id,
            "field_key": field_key,
            "field_label": field_label,
            "ai_value": ai_value,
            "human_value": final_human_value,
            "previous_status": previous_status,
            "validation_status": validation_status,
            "reviewer_id": reviewer_id,
            "reviewer_notes": reviewer_notes,
            "agreement_with_ai": (
                final_human_value == ai_value
                if validation_status != "rejected"
                else False
            ),
        }

        log_audit(
            task_id=task_id,
            step="human_data_extraction",
            subagent="human_reviewer",
            verdict=validation_status,
            confidence=None,
            details={
                "extraction_id": db_extraction_id,
                "review_id": review_id,
                "article_id": article_id,
                "field_key": field_key,
                "previous_status": previous_status,
                "validation_status": validation_status,
                "reviewer_id": reviewer_id,
            },
        )

        log_review_audit(
            project_id=project_id,
            review_id=review_id,
            article_id=article_id,
            extraction_id=db_extraction_id,
            action="human_extraction_validation",
            actor_type="human",
            actor_id=reviewer_id,
            stage="data_extraction",
            before_state={
                "validation_status": previous_status,
                "human_value": None,
            },
            after_state={
                "validation_status": validation_status,
                "human_value": final_human_value,
            },
            details={
                "field_id": field_id,
                "field_key": field_key,
                "field_label": field_label,
                "ai_value": ai_value,
                "reviewer_notes": reviewer_notes,
                "agreement_with_ai": (
                    final_human_value == ai_value
                    if validation_status != "rejected"
                    else False
                ),
            },
        )

        logger.info(
            "task_id=%s — Extracción validada: %s — "
            "campo %s — PMID %s",
            task_id,
            validation_status,
            field_key,
            pmid,
        )

        set_status(
            task_id,
            "completed",
            result=result,
        )

        return result

    except Exception as exc:
        logger.exception(
            "task_id=%s — Error en validación humana "
            "de extracción",
            task_id,
        )

        set_status(
            task_id,
            "failed",
            error=str(exc),
        )

        raise