import logging
import os
import sys
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from db.db import get_conn, log_review_audit, set_status

QUEUE_NAME = "human_screening"
QUEUE_TIMEOUT = 120

logger = logging.getLogger(__name__)

VALID_DECISIONS = {"include", "exclude", "uncertain"}
VALID_STAGES = {"title_abstract", "full_text"}


def _resolve_article(
    cur,
    *,
    project_id,
    review_id,
    article_id=None,
    pmid=None,
):
    if not project_id:
        raise ValueError("project_id es obligatorio")

    if not review_id:
        raise ValueError("review_id es obligatorio")

    if article_id:
        cur.execute(
            """
            SELECT
                ra.id,
                ra.review_id,
                ra.pmid,
                ra.title,
                ra.ai_decision
            FROM review_articles ra
            JOIN systematic_reviews sr
              ON sr.id = ra.review_id
            WHERE ra.id = %s
              AND ra.review_id = %s
              AND sr.project_id = %s
            """,
            (article_id, review_id, project_id),
        )

    elif pmid:
        cur.execute(
            """
            SELECT
                ra.id,
                ra.review_id,
                ra.pmid,
                ra.title,
                ra.ai_decision
            FROM review_articles ra
            JOIN systematic_reviews sr
              ON sr.id = ra.review_id
            WHERE ra.review_id = %s
              AND ra.pmid = %s
              AND sr.project_id = %s
            """,
            (review_id, pmid, project_id),
        )

    else:
        raise ValueError("Debes indicar article_id o pmid")

    article = cur.fetchone()

    if not article:
        raise ValueError(
            "Artículo no encontrado en la revisión y proyecto indicados"
        )

    return article


def _refresh_consensus(cur, review_id, article_id, stage):
    cur.execute(
        """
        SELECT
            reviewer_id,
            decision,
            exclusion_reason_code,
            reason
        FROM review_screening_decisions
        WHERE review_id = %s
          AND article_id = %s
          AND stage = %s
        ORDER BY created_at, reviewer_id
        """,
        (review_id, article_id, stage),
    )

    decisions = cur.fetchall()

    if len(decisions) < 2:
        return {
            "consensus": False,
            "conflict": False,
            "decision_count": len(decisions),
            "final_decision": None,
        }

    decision_values = {
        row[1]
        for row in decisions
    }

    # Solo existe consenso automático si TODAS las decisiones coinciden.
    if len(decision_values) == 1:
        consensus_decision = decisions[0][1]

        exclusion_code = None
        exclusion_reason = None

        if consensus_decision == "exclude":
            exclusion_code = next(
                (
                    row[2]
                    for row in decisions
                    if row[2]
                ),
                None,
            )

            exclusion_reason = next(
                (
                    row[3]
                    for row in decisions
                    if row[3]
                ),
                None,
            )

        cur.execute(
            """
            DELETE FROM review_screening_conflicts
            WHERE review_id = %s
              AND article_id = %s
              AND stage = %s
            """,
            (review_id, article_id, stage),
        )

        if stage == "title_abstract":
            next_full_text_status = (
                "pending"
                if consensus_decision in {"include", "uncertain"}
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
                    consensus_decision,
                    next_full_text_status,
                    consensus_decision,
                    exclusion_code,
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
                    consensus_decision,
                    consensus_decision,
                    consensus_decision,
                    exclusion_code,
                    exclusion_reason,
                    article_id,
                    review_id,
                ),
            )

        return {
            "consensus": True,
            "conflict": False,
            "decision_count": len(decisions),
            "final_decision": consensus_decision,
        }

    # Existe al menos una discrepancia: abrir o reabrir conflicto.
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
            review_id = EXCLUDED.review_id,
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
              AND review_id = %s
            """,
            (article_id, review_id),
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
              AND review_id = %s
            """,
            (article_id, review_id),
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
        project_id = payload.get("project_id")
        pmid = payload.get("pmid")

        reviewer_id = (payload.get("reviewer_id") or "").strip()
        stage = (payload.get("stage") or "title_abstract").strip().lower()
        decision = (payload.get("decision") or "").strip().lower()

        exclusion_reason = payload.get("exclusion_reason")
        exclusion_reason_code = payload.get("exclusion_reason_code")
        notes = payload.get("notes")

        if not project_id:
            raise ValueError("project_id es obligatorio")

        if not review_id:
            raise ValueError("review_id es obligatorio")

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
                    project_id=project_id,
                    review_id=review_id,
                    article_id=article_id,
                    pmid=pmid,
                )

                (
                    db_article_id,
                    db_review_id,
                    db_pmid,
                    title,
                    ai_decision,
                ) = article

                cur.execute(
                    """
                    SELECT
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
                    """,
                    (db_article_id, db_review_id),
                )
                audit_before = cur.fetchone()

                if not audit_before:
                    raise ValueError(
                        "No se pudo obtener el contexto de auditoría del artículo"
                    )

                (
                    project_id,
                    before_title_abstract_status,
                    before_full_text_status,
                    before_human_decision,
                    before_final_decision,
                    before_screening_status,
                    before_screening_stage,
                ) = audit_before

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
                    (db_article_id,),
                )
                audit_after = cur.fetchone()

                log_review_audit(
                    project_id=project_id,
                    review_id=db_review_id,
                    article_id=db_article_id,
                    action="human_screening_decision",
                    actor_type="human",
                    actor_id=reviewer_id,
                    stage=stage,
                    before_state={
                        "title_abstract_status": before_title_abstract_status,
                        "full_text_status": before_full_text_status,
                        "human_decision": before_human_decision,
                        "final_decision": before_final_decision,
                        "screening_status": before_screening_status,
                        "screening_stage": before_screening_stage,
                    },
                    after_state={
                        "title_abstract_status": audit_after[0],
                        "full_text_status": audit_after[1],
                        "human_decision": audit_after[2],
                        "final_decision": audit_after[3],
                        "screening_status": audit_after[4],
                        "screening_stage": audit_after[5],
                    },
                    details={
                        "decision": decision,
                        "exclusion_reason": exclusion_reason,
                        "exclusion_reason_code": exclusion_reason_code,
                        "notes": notes,
                        "consensus": consensus,
                        "ai_decision": ai_decision,
                    },
                    conn=conn,
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
