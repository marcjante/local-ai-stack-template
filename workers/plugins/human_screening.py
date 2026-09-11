import logging
import os
import sys
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from db.db import get_conn, set_status

QUEUE_NAME = "human_screening"
QUEUE_TIMEOUT = 120

logger = logging.getLogger(__name__)

VALID_DECISIONS = {"include", "exclude", "uncertain"}
VALID_STAGES = {"title_abstract", "full_text"}


def _resolve_article(cur, article_id=None, review_id=None, pmid=None):
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
        raise ValueError("Debes indicar article_id o review_id + pmid")

    article = cur.fetchone()

    if not article:
        raise ValueError("Artículo no encontrado")

    return article


def _refresh_consensus(cur, review_id, article_id, stage):
    cur.execute(
        """
        SELECT reviewer_id, decision, exclusion_reason_code, reason
        FROM review_screening_decisions
        WHERE article_id = %s
          AND stage = %s
        ORDER BY created_at, reviewer_id
        """,
        (article_id, stage),
    )

    decisions = cur.fetchall()

    if len(decisions) < 2:
        return {
            "consensus": False,
            "conflict": False,
            "decision_count": len(decisions),
            "final_decision": None,
        }

    first = decisions[0]
    second = decisions[1]

    if first[1] == second[1]:
        consensus_decision = first[1]

        cur.execute(
            """
            DELETE FROM review_screening_conflicts
            WHERE article_id = %s
              AND stage = %s
            """,
            (article_id, stage),
        )

        if stage == "title_abstract":
            next_full_text_status = (
                "pending"
                if consensus_decision in {"include", "uncertain"}
                else "not_started"
            )

            exclusion_code = (
                first[2] or second[2]
                if consensus_decision == "exclude"
                else None
            )

            cur.execute(
                """
                UPDATE review_articles
                SET
                    title_abstract_status = %s,
                    full_text_status = %s,
                    human_decision = %s,
                    exclusion_reason_code = %s,
                    exclusion_reason = CASE
                        WHEN %s = 'exclude' THEN COALESCE(%s, %s)
                        ELSE NULL
                    END,
                    screening_status = 'reviewed',
                    screening_stage = 'title_abstract',
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    consensus_decision,
                    next_full_text_status,
                    consensus_decision,
                    exclusion_code,
                    consensus_decision,
                    first[3],
                    second[3],
                    article_id,
                ),
            )

        else:
            exclusion_code = (
                first[2] or second[2]
                if consensus_decision == "exclude"
                else None
            )

            cur.execute(
                """
                UPDATE review_articles
                SET
                    full_text_status = %s,
                    final_decision = %s,
                    human_decision = %s,
                    exclusion_reason_code = %s,
                    exclusion_reason = CASE
                        WHEN %s = 'exclude' THEN COALESCE(%s, %s)
                        ELSE NULL
                    END,
                    screening_status = 'reviewed',
                    screening_stage = 'full_text',
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    consensus_decision,
                    consensus_decision,
                    consensus_decision,
                    exclusion_code,
                    consensus_decision,
                    first[3],
                    second[3],
                    article_id,
                ),
            )

        return {
            "consensus": True,
            "conflict": False,
            "decision_count": len(decisions),
            "final_decision": consensus_decision,
        }

    conflict_id = str(uuid.uuid4())

    cur.execute(
        """
        INSERT INTO review_screening_conflicts (
            id,
            review_id,
            article_id,
            stage,
            status
        )
        VALUES (%s, %s, %s, %s, 'open')
        ON CONFLICT (article_id, stage)
        DO UPDATE SET
            status = 'open',
            resolution = NULL,
            resolved_by = NULL,
            resolution_notes = NULL,
            resolved_at = NULL
        """,
        (
            conflict_id,
            review_id,
            article_id,
            stage,
        ),
    )

    if stage == "title_abstract":
        cur.execute(
            """
            UPDATE review_articles
            SET
                title_abstract_status = 'conflict',
                screening_status = 'conflict',
                screening_stage = 'title_abstract',
                updated_at = NOW()
            WHERE id = %s
            """,
            (article_id,),
        )
    else:
        cur.execute(
            """
            UPDATE review_articles
            SET
                full_text_status = 'conflict',
                screening_status = 'conflict',
                screening_stage = 'full_text',
                updated_at = NOW()
            WHERE id = %s
            """,
            (article_id,),
        )

    return {
        "consensus": False,
        "conflict": True,
        "decision_count": len(decisions),
        "final_decision": None,
    }


def handle(task_id, payload):
    set_status(task_id, "running")

    try:
        article_id = payload.get("article_id")
        review_id = payload.get("review_id")
        pmid = payload.get("pmid")

        reviewer_id = (payload.get("reviewer_id") or "").strip()
        stage = (payload.get("stage") or "title_abstract").strip().lower()
        decision = (payload.get("decision") or "").strip().lower()

        exclusion_reason = payload.get("exclusion_reason")
        exclusion_reason_code = payload.get("exclusion_reason_code")
        notes = payload.get("notes")

        if not reviewer_id:
            raise ValueError("reviewer_id es obligatorio")

        if stage not in VALID_STAGES:
            raise ValueError(
                "stage debe ser title_abstract o full_text"
            )

        if decision not in VALID_DECISIONS:
            raise ValueError(
                "decision debe ser include, exclude o uncertain"
            )

        if decision == "exclude" and not (exclusion_reason or exclusion_reason_code):
            raise ValueError(
                "Cuando decision=exclude debes indicar exclusion_reason "
                "o exclusion_reason_code"
            )

        if decision != "exclude":
            exclusion_reason = None
            exclusion_reason_code = None

        with get_conn() as conn:
            with conn.cursor() as cur:
                article = _resolve_article(
                    cur,
                    article_id=article_id,
                    review_id=review_id,
                    pmid=pmid,
                )

                (
                    db_article_id,
                    db_review_id,
                    db_pmid,
                    title,
                    ai_decision,
                ) = article

                decision_id = str(uuid.uuid4())

                cur.execute(
                    """
                    INSERT INTO review_screening_decisions (
                        id,
                        review_id,
                        article_id,
                        stage,
                        reviewer_id,
                        decision,
                        exclusion_reason_code,
                        reason,
                        notes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (article_id, stage, reviewer_id)
                    DO UPDATE SET
                        decision = EXCLUDED.decision,
                        exclusion_reason_code = EXCLUDED.exclusion_reason_code,
                        reason = EXCLUDED.reason,
                        notes = EXCLUDED.notes,
                        updated_at = NOW()
                    """,
                    (
                        decision_id,
                        db_review_id,
                        db_article_id,
                        stage,
                        reviewer_id,
                        decision,
                        exclusion_reason_code,
                        exclusion_reason,
                        notes,
                    ),
                )

                consensus = _refresh_consensus(
                    cur,
                    db_review_id,
                    db_article_id,
                    stage,
                )

        agreement_with_ai = None
        if stage == "title_abstract" and ai_decision:
            agreement_with_ai = ai_decision == decision

        result = {
            "article_id": db_article_id,
            "review_id": db_review_id,
            "pmid": db_pmid,
            "title": title,
            "stage": stage,
            "reviewer_id": reviewer_id,
            "decision": decision,
            "ai_decision": ai_decision,
            "agreement_with_ai": agreement_with_ai,
            "exclusion_reason": exclusion_reason,
            "exclusion_reason_code": exclusion_reason_code,
            **consensus,
        }

        logger.info(
            "task_id=%s — Screening humano guardado: artículo=%s "
            "stage=%s reviewer=%s decision=%s conflict=%s",
            task_id,
            db_article_id,
            stage,
            reviewer_id,
            decision,
            consensus["conflict"],
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
