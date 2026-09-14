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


def _call_screening_model(prompt, strict_retry=False):
    system = (
        "Eres un asistente metodológico conservador para revisiones "
        "sistemáticas. No inventes datos. Responde solo JSON válido."
    )

    if strict_retry:
        system += (
            " Tu respuesta anterior no pudo procesarse. "
            "Responde únicamente con un objeto JSON, sin markdown, "
            "sin texto antes ni después y sin explicaciones adicionales."
        )

        prompt += """
REINTENTO ESTRICTO DE FORMATO.

Devuelve únicamente un objeto JSON con esta estructura:
{
  "decision": "include",
  "reason": "justificación breve",
  "confidence": 0.5
}

Los únicos valores válidos para decision son:
include
exclude
uncertain

No añadas ninguna otra frase.
"""

    response = requests.post(
        f"{LLM_GATEWAY_URL}/generate",
        json={
            "task_type": "rapido",
            "skill_task": "screening",
            "prompt": prompt,
            "system": system,
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

    return payload


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

    payload = _call_screening_model(prompt)

    try:
        parsed = _extract_json(payload.get("response", ""))
    except (ValueError, json.JSONDecodeError) as first_exc:
        log.warning(
            "Primer intento de screening sin JSON válido; "
            f"reintentando en formato estricto. Error: {first_exc}"
        )
        payload = _call_screening_model(prompt, strict_retry=True)
        parsed = _extract_json(payload.get("response", ""))

    decision = str(parsed.get("decision", "uncertain")).strip().lower()

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
        "_skill_task": payload.get("_skill_task"),
        "_skills_used": payload.get("_skills_used", []),
    }


def handle(task_id: str, payload: dict) -> dict:
    review_id = payload.get("review_id")
    project_id = payload.get("project_id")

    if not review_id:
        raise ValueError("Falta el campo 'review_id'")

    if not project_id:
        raise ValueError("Falta el campo 'project_id'")

    set_status(task_id, "running", increment_attempts=True)

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
                  AND project_id = %s
                """,
                (review_id, project_id),
            )

            row = cur.fetchone()

            if not row:
                raise ValueError(f"No existe la revisión {review_id}")

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
                    ra.id,
                    ra.title,
                    ra.abstract
                FROM review_articles ra
                JOIN systematic_reviews sr
                  ON sr.id = ra.review_id
                WHERE ra.review_id = %s
                  AND sr.project_id = %s
                  AND ra.is_duplicate = false
                  AND ra.title_abstract_status = 'pending'
                  AND ra.ai_decision IS NULL
                ORDER BY ra.created_at
                """,
                (review_id, project_id),
            )

            articles = cur.fetchall()
            results = []
            errors = []

            for article_id, title, abstract in articles:
                article = {
                    "id": article_id,
                    "title": title or "",
                    "abstract": abstract or "",
                }

                try:
                    screening_result = _ai_screen(article, review)
                except Exception as exc:
                    log.exception(
                        f"Fallo screening IA artículo {article_id}: {exc}",
                        extra={"task_id": task_id},
                    )

                    errors.append(
                        {
                            "article_id": article_id,
                            "title": title,
                            "error": str(exc),
                        }
                    )

                    # No se guarda ninguna decisión inventada.
                    # El artículo conserva ai_decision = NULL para poder reintentarlo.
                    continue

                cur.execute(
                    """
                    UPDATE review_articles
                    SET
                        ai_decision = %s,
                        ai_reason = %s,
                        ai_confidence = %s,
                        screening_stage = 'title_abstract',
                        updated_at = now()
                    WHERE id = %s
                      AND review_id = %s
                    """,
                    (
                        screening_result["decision"],
                        screening_result["reason"],
                        screening_result["confidence"],
                        article_id,
                        review_id,
                    ),
                )

                results.append(
                    {
                        "article_id": article_id,
                        "title": title,
                        **screening_result,
                    }
                )

        result = {
            "review_id": review_id,
            "stage": "title_abstract",
            "screened": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
        }

        set_status(task_id, "completed", result=result)

        log.info(
            "Screening IA completado: "
            f"{len(results)} procesados correctamente, "
            f"{len(errors)} con error",
            extra={"task_id": task_id},
        )

        return result

    except Exception as exc:
        set_status(task_id, "failed", error=str(exc))
        log.error(
            f"Screening IA falló: {exc}",
            extra={"task_id": task_id},
        )
        raise
