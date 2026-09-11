import json
import logging
import os
import re
import sys
import uuid

import requests
from psycopg2.extras import Json

sys.path.append(
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../..")
    )
)

from db.db import get_conn, log_audit, set_status


QUEUE_NAME = "data_extraction"
QUEUE_TIMEOUT = 600

LLM_GATEWAY_URL = os.getenv(
    "LLM_GATEWAY_URL",
    "http://127.0.0.1:8091",
).rstrip("/")

logger = logging.getLogger(__name__)


def _extract_json(text):
    """
    Intenta recuperar un objeto JSON de la respuesta del LLM.
    """

    if isinstance(text, dict):
        return text

    if not text:
        raise ValueError("El LLM no devolvió contenido")

    text = str(text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)

    if not match:
        raise ValueError(
            "No se pudo encontrar un objeto JSON en la respuesta del LLM"
        )

    return json.loads(match.group(0))


def _gateway_text(data):
    """
    Recupera el texto generado tolerando distintas versiones
    del contrato del LLM Gateway.
    """

    for key in (
        "response",
        "text",
        "content",
        "answer",
        "output",
        "generated_text",
    ):
        value = data.get(key)

        if isinstance(value, str) and value.strip():
            return value

    message = data.get("message")

    if isinstance(message, dict):
        content = message.get("content")

        if isinstance(content, str) and content.strip():
            return content

    raise ValueError(
        "La respuesta del LLM Gateway no contiene texto generado"
    )


def _normalise_confidence(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    return max(0.0, min(1.0, value))


def _validate_source_quote(source_quote, abstract):
    """
    Solo conserva una cita si aparece literalmente en el abstract.

    Esto evita guardar como evidencia una cita inventada
    o parafraseada por el modelo.
    """

    if not source_quote:
        return None

    quote = str(source_quote).strip()

    if not quote:
        return None

    abstract = abstract or ""

    if quote in abstract:
        return quote

    return None


def _load_extraction_context(review_id, article_ids=None):
    """
    Recupera:
    - revisión,
    - campos de extracción,
    - artículos incluidos por decisión humana.

    La conexión se cierra antes de llamar al LLM.
    """

    with get_conn() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT id, title
                FROM systematic_reviews
                WHERE id = %s
                """,
                (review_id,),
            )

            review = cur.fetchone()

            if not review:
                raise ValueError(
                    f"Revisión no encontrada: {review_id}"
                )

            cur.execute(
                """
                SELECT
                    id,
                    field_key,
                    label,
                    description,
                    value_type,
                    required,
                    display_order
                FROM review_extraction_fields
                WHERE review_id = %s
                ORDER BY display_order, field_key
                """,
                (review_id,),
            )

            field_rows = cur.fetchall()

            if not field_rows:
                raise ValueError(
                    "La revisión no tiene campos de extracción configurados"
                )

            fields = [
                {
                    "id": row[0],
                    "field_key": row[1],
                    "label": row[2],
                    "description": row[3],
                    "value_type": row[4],
                    "required": row[5],
                    "display_order": row[6],
                }
                for row in field_rows
            ]

            params = [review_id]

            sql = """
                SELECT
                    id,
                    pmid,
                    doi,
                    title,
                    abstract,
                    human_decision,
                    screening_status
                FROM review_articles
                WHERE review_id = %s
                  AND human_decision = 'include'
                  AND screening_status = 'reviewed'
            """

            if article_ids:
                sql += " AND id = ANY(%s)"
                params.append(article_ids)

            sql += " ORDER BY created_at, id"

            cur.execute(sql, params)

            article_rows = cur.fetchall()

            articles = [
                {
                    "id": row[0],
                    "pmid": row[1],
                    "doi": row[2],
                    "title": row[3],
                    "abstract": row[4],
                    "human_decision": row[5],
                    "screening_status": row[6],
                }
                for row in article_rows
            ]

    return {
        "review": {
            "id": review[0],
            "title": review[1],
        },
        "fields": fields,
        "articles": articles,
    }


def _extract_field(article, field):
    """
    Solicita al LLM una propuesta para UN campo y UN artículo.

    Actualmente la única fuente documental disponible es el abstract.
    El modelo tiene prohibido inferir datos ausentes.
    """

    abstract = article.get("abstract") or ""

    prompt = f"""
Eres un asistente de extracción de datos para revisiones sistemáticas.

Tu tarea es PROPONER una extracción estructurada.
NO estás tomando una decisión científica definitiva.

FUENTE DISPONIBLE:
Únicamente el título y el abstract proporcionados abajo.

REGLAS OBLIGATORIAS:
1. No inventes información.
2. No uses conocimiento externo.
3. No supongas que tienes acceso al texto completo.
4. Si el dato no aparece explícitamente, devuelve value=null.
5. Si aportas source_quote, debe ser una cita LITERAL del abstract.
6. confidence debe estar entre 0 y 1.
7. La propuesta será posteriormente revisada por una persona.

ARTÍCULO
Título:
{article.get("title") or ""}

Abstract:
{abstract}

CAMPO A EXTRAER
Clave: {field.get("field_key")}
Nombre: {field.get("label")}
Descripción: {field.get("description") or ""}
Tipo esperado: {field.get("value_type")}
Obligatorio en el formulario: {field.get("required")}

Devuelve exclusivamente JSON válido con esta estructura:

{{
  "value": null,
  "reason": "explicación breve basada únicamente en el abstract",
  "confidence": 0.0,
  "source_quote": null
}}
""".strip()

    response = requests.post(
        f"{LLM_GATEWAY_URL}/generate",
        json={
            "task_type": "razonamiento",
            "skill_task": "data_extraction",
            "prompt": prompt,
            "temperature": 0,
        },
        timeout=180,
    )

    response.raise_for_status()

    gateway_data = response.json()

    raw_text = _gateway_text(gateway_data)
    extraction = _extract_json(raw_text)

    value = extraction.get("value")
    reason = extraction.get("reason")
    confidence = _normalise_confidence(
        extraction.get("confidence")
    )

    proposed_quote = extraction.get("source_quote")

    verified_quote = _validate_source_quote(
        proposed_quote,
        abstract,
    )

    quote_verified = (
        proposed_quote is None
        or verified_quote is not None
    )

    if proposed_quote and not verified_quote:
        reason = (
            f"{reason or ''} "
            "[La cita propuesta por la IA no pudo verificarse "
            "literalmente en el abstract y no se ha guardado.]"
        ).strip()

    return {
        "value": value,
        "reason": reason,
        "confidence": confidence,
        "source_quote": verified_quote,
        "quote_verified": quote_verified,
        "model": gateway_data.get("_model_used"),
        "provider": gateway_data.get("_provider_used"),
        "skill_task": gateway_data.get("_skill_task"),
        "skills_used": gateway_data.get("_skills_used") or [],
    }


def _save_extraction(
    review_id,
    article,
    field,
    proposal,
):
    """
    Guarda una propuesta de IA sin sobrescribir silenciosamente
    una extracción que ya haya sido validada por una persona.
    """

    extraction_id = str(uuid.uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    id,
                    validation_status,
                    human_value
                FROM review_extractions
                WHERE article_id = %s
                  AND field_id = %s
                """,
                (
                    article["id"],
                    field["id"],
                ),
            )

            existing = cur.fetchone()

            if existing:
                existing_id = existing[0]
                validation_status = existing[1]

                if validation_status != "pending":
                    return {
                        "id": existing_id,
                        "saved": False,
                        "skipped": True,
                        "reason": (
                            "La extracción ya tiene validación humana "
                            f"({validation_status})"
                        ),
                    }

                cur.execute(
                    """
                    UPDATE review_extractions
                    SET
                        ai_value = %s,
                        ai_reason = %s,
                        ai_confidence = %s,
                        source_type = 'abstract',
                        source_location = 'abstract',
                        source_quote = %s,
                        model = %s,
                        provider = %s,
                        skills_used = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        Json(proposal["value"]),
                        proposal["reason"],
                        proposal["confidence"],
                        proposal["source_quote"],
                        proposal["model"],
                        proposal["provider"],
                        Json(proposal["skills_used"]),
                        existing_id,
                    ),
                )

                return {
                    "id": existing_id,
                    "saved": True,
                    "updated": True,
                    "skipped": False,
                }

            cur.execute(
                """
                INSERT INTO review_extractions (
                    id,
                    review_id,
                    article_id,
                    field_id,
                    ai_value,
                    ai_reason,
                    ai_confidence,
                    source_type,
                    source_location,
                    source_quote,
                    validation_status,
                    model,
                    provider,
                    skills_used
                )
                VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    'abstract',
                    'abstract',
                    %s,
                    'pending',
                    %s, %s, %s
                )
                """,
                (
                    extraction_id,
                    review_id,
                    article["id"],
                    field["id"],
                    Json(proposal["value"]),
                    proposal["reason"],
                    proposal["confidence"],
                    proposal["source_quote"],
                    proposal["model"],
                    proposal["provider"],
                    Json(proposal["skills_used"]),
                ),
            )

    return {
        "id": extraction_id,
        "saved": True,
        "updated": False,
        "skipped": False,
    }


def handle(task_id, payload):
    set_status(task_id, "running")

    try:
        review_id = payload.get("review_id")

        if not review_id:
            raise ValueError(
                "review_id es obligatorio"
            )

        article_ids = payload.get("article_ids")

        if article_ids is not None:
            if not isinstance(article_ids, list):
                raise ValueError(
                    "article_ids debe ser una lista"
                )

            article_ids = [
                str(article_id)
                for article_id in article_ids
                if article_id
            ]

        context = _load_extraction_context(
            review_id=review_id,
            article_ids=article_ids,
        )

        review = context["review"]
        fields = context["fields"]
        articles = context["articles"]

        if not articles:
            raise ValueError(
                "No hay artículos incluidos por decisión humana "
                "disponibles para extracción"
            )

        results = []
        errors = []

        for article in articles:

            if not article.get("abstract"):
                errors.append(
                    {
                        "article_id": article["id"],
                        "pmid": article.get("pmid"),
                        "error": (
                            "El artículo no dispone de abstract. "
                            "No se ha intentado extraer información."
                        ),
                    }
                )
                continue

            for field in fields:

                try:
                    proposal = _extract_field(
                        article,
                        field,
                    )

                    saved = _save_extraction(
                        review_id,
                        article,
                        field,
                        proposal,
                    )

                    result_item = {
                        "extraction_id": saved["id"],
                        "article_id": article["id"],
                        "pmid": article.get("pmid"),
                        "field_id": field["id"],
                        "field_key": field["field_key"],
                        "field_label": field["label"],
                        "ai_value": proposal["value"],
                        "ai_confidence": proposal["confidence"],
                        "source_type": "abstract",
                        "source_location": "abstract",
                        "source_quote": proposal["source_quote"],
                        "quote_verified": proposal["quote_verified"],
                        "validation_status": "pending",
                        "saved": saved["saved"],
                        "skipped": saved["skipped"],
                        "model": proposal["model"],
                        "provider": proposal["provider"],
                        "skills_used": proposal["skills_used"],
                    }

                    if saved.get("reason"):
                        result_item["skip_reason"] = saved["reason"]

                    results.append(result_item)

                except Exception as field_exc:
                    logger.exception(
                        "task_id=%s — Error extrayendo artículo=%s campo=%s",
                        task_id,
                        article["id"],
                        field["field_key"],
                    )

                    errors.append(
                        {
                            "article_id": article["id"],
                            "pmid": article.get("pmid"),
                            "field_id": field["id"],
                            "field_key": field["field_key"],
                            "error": str(field_exc),
                        }
                    )

        result = {
            "review_id": review_id,
            "review_title": review["title"],
            "source_scope": "title_abstract_only",
            "articles_selected": len(articles),
            "fields_configured": len(fields),
            "possible_extractions": (
                len(articles) * len(fields)
            ),
            "results_count": len(results),
            "errors_count": len(errors),
            "results": results,
            "errors": errors,
            "human_review_required": True,
        }

        log_audit(
            task_id=task_id,
            step="data_extraction",
            subagent="data_extraction",
            verdict="proposal_generated",
            details={
                "review_id": review_id,
                "articles_selected": len(articles),
                "fields_configured": len(fields),
                "results_count": len(results),
                "errors_count": len(errors),
                "source_scope": "title_abstract_only",
                "human_review_required": True,
            },
        )

        set_status(
            task_id,
            "completed",
            result=result,
        )

        return result

    except Exception as exc:
        logger.exception(
            "task_id=%s — Error en data extraction",
            task_id,
        )

        set_status(
            task_id,
            "failed",
            error=str(exc),
        )

        raise