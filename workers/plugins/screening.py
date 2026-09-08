import json
import os
import re
import sys

import requests

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from db.db import get_conn, set_status
from common.logging_setup import get_logger

log = get_logger(__name__)

QUEUE_NAME = "screening"
QUEUE_TIMEOUT = 300

LLM_GATEWAY_URL = os.environ.get(
    "LLM_GATEWAY_URL",
    "http://127.0.0.1:8091"
)


def _extract_json(text):
    text = (text or "").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)

    if not match:
        raise ValueError(
            f"El modelo no devolvió JSON válido: {text[:300]}"
        )

    return json.loads(match.group(0))


def _ai_screen(article, review):
    prompt = f"""
Eres un asistente metodológico para screening de revisiones sistemáticas.

Tu función es PROPONER una decisión para revisión humana.
Nunca tomes una decisión definitiva por tu cuenta.

PREGUNTA DE INVESTIGACIÓN:
{review["research_question"] or "No especificada"}

PICO / PECO

Población:
{review["population"] or "No especificada"}

Intervención / exposición:
{review["intervention"] or "No especificada"}

Comparador:
{review["comparator"] or "No especificado"}

Outcomes:
{review["outcomes"] or "No especificados"}

CRITERIOS DE INCLUSIÓN:
{review["inclusion_criteria"] or "No especificados"}

CRITERIOS DE EXCLUSIÓN:
{review["exclusion_criteria"] or "No especificados"}

ARTÍCULO

Título:
{article["title"] or ""}

Abstract:
{article["abstract"] or "NO DISPONIBLE"}

Reglas:

1. Evalúa únicamente título y abstract.
2. Usa "include" si parece cumplir razonablemente los criterios.
3. Usa "exclude" solo si existe evidencia clara de incumplimiento.
4. Usa "uncertain" si falta información o existe duda.
5. Si no hay abstract, evita excluir salvo que el título lo justifique claramente.
6. No inventes información.
7. La confianza debe estar entre 0.0 y 1.0.
8. La decisión es una PROPUESTA para revisión humana, no una decisión final.

Devuelve EXCLUSIVAMENTE JSON válido:

{{
  "decision": "include",
  "reason": "Explicación breve basada en título y abstract.",
  "confidence": 0.85
}}

Los únicos valores permitidos para decision son:
include
exclude
uncertain
"""

    response = requests.post(
        f"{LLM_GATEWAY_URL}/generate",
        json={
            "task_type": "rapido",
            "prompt": prompt,
            "system": (
                "Eres un asistente metodológico conservador para revisiones "
                "sistemáticas. No inventes datos. Responde solo JSON válido."
            ),
            "temperature": 0,
        },
        timeout=180,
    )

    if not response.ok:
        raise RuntimeError(
            f"Gateway HTTP {response.status_code}: {response.text[:500]}"
        )

    payload = response.json()

    if "error" in payload:
        raise RuntimeError(payload["error"])

    parsed = _extract_json(payload.get("response", ""))

    decision = str(
        parsed.get("decision", "uncertain")
    ).strip().lower()

    if decision not in {"include", "exclude", "uncertain"}:
        decision = "uncertain"

    reason = str(
        parsed.get(
            "reason",
            "El modelo no proporcionó una justificación válida."
        )
    ).strip()

    try:
        confidence = float(parsed.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5

    confidence = max(0.0, min(1.0, confidence))

    return {
        "decision": decision,
        "reason": reason,
        "confidence": confidence,
        "model": payload.get("_model_used"),
        "provider": payload.get("_provider_used"),
    }


def handle(task_id: str, payload: dict) -> dict:
    review_id = payload.get("review_id")

    if not review_id:
        raise ValueError("Falta el campo 'review_id'")

    set_status(
        task_id,
        "running",
        increment_attempts=True
    )

    try:
        with get_conn() as conn, conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    research_question,
                    population,
                    intervention,
                    comparator,
                    outcomes,
                    inclusion_criteria,
                    exclusion_criteria
                FROM systematic_reviews
                WHERE id = %s
                """,
                (review_id,),
            )

            row = cur.fetchone()

            if not row:
                raise ValueError(
                    f"No existe la revisión {review_id}"
                )

            review = {
                "research_question": row[0],
                "population": row[1],
                "intervention": row[2],
                "comparator": row[3],
                "outcomes": row[4],
                "inclusion_criteria": row[5],
                "exclusion_criteria": row[6],
            }

            cur.execute(
                """
                SELECT
                    id,
                    title,
                    abstract
                FROM review_articles
                WHERE review_id = %s
                  AND screening_status = 'pending'
                  AND ai_decision IS NULL
                ORDER BY created_at
                """,
                (review_id,),
            )

            articles = cur.fetchall()

            results = []

            for article_id, title, abstract in articles:

                article = {
                    "id": article_id,
                    "title": title or "",
                    "abstract": abstract or "",
                }

                try:
                    screening = _ai_screen(
                        article,
                        review
                    )

                except Exception as exc:
                    log.exception(
                        f"Fallo screening IA artículo {article_id}: {exc}",
                        extra={"task_id": task_id},
                    )

                    raise RuntimeError(
                        "Screening IA detenido porque no se pudo consultar "
                        f"correctamente el modelo para el artículo {article_id}. "
                        "No se ha guardado ninguna decisión IA para este artículo. "
                        f"Error: {exc}"
                    ) from exc

                cur.execute(
                    """
                    UPDATE review_articles
                    SET
                        ai_decision = %s,
                        ai_reason = %s,
                        ai_confidence = %s,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        screening["decision"],
                        screening["reason"],
                        screening["confidence"],
                        article_id,
                    ),
                )

                results.append(
                    {
                        "article_id": article_id,
                        "title": title,
                        **screening,
                    }
                )

        result = {
            "review_id": review_id,
            "screened": len(results),
            "results": results,
        }

        set_status(
            task_id,
            "completed",
            result=result
        )

        log.info(
            f"Screening IA completado: {len(results)} artículos",
            extra={"task_id": task_id},
        )

        return result

    except Exception as exc:

        set_status(
            task_id,
            "failed",
            error=str(exc)
        )

        log.error(
            f"Screening IA falló: {exc}",
            extra={"task_id": task_id},
        )

        raise
