import logging
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from db.db import get_conn, set_status

QUEUE_NAME = "human_screening"
QUEUE_TIMEOUT = 120

logger = logging.getLogger(__name__)


def handle(task_id, payload):
    set_status(task_id, "running")

    try:
        article_id = payload.get("article_id")
        review_id = payload.get("review_id")
        pmid = payload.get("pmid")

        decision = (payload.get("decision") or "").strip().lower()
        exclusion_reason = payload.get("exclusion_reason")

        if decision not in {"include", "exclude", "uncertain"}:
            raise ValueError(
                "decision debe ser include, exclude o uncertain"
            )

        if decision == "exclude" and not exclusion_reason:
            raise ValueError(
                "exclusion_reason es obligatorio cuando decision=exclude"
            )

        if decision != "exclude":
            exclusion_reason = None

        with get_conn() as conn:
            with conn.cursor() as cur:

                if article_id:
                    cur.execute(
                        """
                        SELECT id, review_id, pmid, title, ai_decision
                        FROM review_articles
                        WHERE id = %s
                        """,
                        (article_id,),
                    )

                elif review_id and pmid:
                    cur.execute(
                        """
                        SELECT id, review_id, pmid, title, ai_decision
                        FROM review_articles
                        WHERE review_id = %s
                          AND pmid = %s
                        """,
                        (review_id, pmid),
                    )

                else:
                    raise ValueError(
                        "Debes indicar article_id o review_id + pmid"
                    )

                article = cur.fetchone()

                if not article:
                    raise ValueError("Artículo no encontrado")

                (
                    db_article_id,
                    db_review_id,
                    db_pmid,
                    title,
                    ai_decision,
                ) = article

                cur.execute(
                    """
                    UPDATE review_articles
                    SET
                        human_decision = %s,
                        exclusion_reason = %s,
                        screening_status = 'reviewed',
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        decision,
                        exclusion_reason,
                        db_article_id,
                    ),
                )

        agreement = None

        if ai_decision:
            agreement = ai_decision == decision

        result = {
            "article_id": db_article_id,
            "review_id": db_review_id,
            "pmid": db_pmid,
            "title": title,
            "ai_decision": ai_decision,
            "human_decision": decision,
            "agreement_with_ai": agreement,
            "exclusion_reason": exclusion_reason,
            "screening_status": "reviewed",
        }

        logger.info(
            "task_id=%s — Decisión humana guardada: %s — PMID %s",
            task_id,
            decision,
            db_pmid,
        )

        set_status(
            task_id,
            "completed",
            result=result,
        )

        return result

    except Exception as exc:
        logger.exception(
            "task_id=%s — Error en human screening",
            task_id,
        )

        set_status(
            task_id,
            "failed",
            error=str(exc),
        )

        raise
