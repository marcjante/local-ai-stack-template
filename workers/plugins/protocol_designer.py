import json
import os
import re
from typing import Any, Dict

import requests

from common.logging_setup import get_logger
from db.db import set_status


QUEUE_NAME = "protocol_designer"
QUEUE_TIMEOUT = 300

GATEWAY_URL = os.getenv(
    "LLM_GATEWAY_URL",
    "http://127.0.0.1:8091",
)

log = get_logger(__name__)


def _extract_json(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("La IA devolvió una respuesta vacía")

    cleaned = text.strip()

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s*```$",
        "",
        cleaned,
    )

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError(
            "La IA no devolvió un objeto JSON reconocible"
        )

    candidate = cleaned[start:end + 1]

    return json.loads(candidate)


def _call_gateway(
    prompt: str,
    route: str = "razonamiento",
) -> Dict[str, Any]:

    try:
        response = requests.post(
            f"{GATEWAY_URL}/generate",
            json={
                "prompt": prompt,
                "route": route,
            },
            timeout=240,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"No se pudo conectar con el LLM Gateway: {exc}"
        ) from exc

    if not response.ok:
        raise RuntimeError(
            f"Gateway HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "El Gateway devolvió una respuesta no válida"
        ) from exc

    raw_response = payload.get("response")

    if not raw_response:
        raise RuntimeError(
            "El Gateway no devolvió contenido generado"
        )

    return payload


def _repair_json(
    broken_text: str,
) -> Dict[str, Any]:

    repair_prompt = f"""
Corrige el siguiente contenido para convertirlo en JSON válido.

REGLAS OBLIGATORIAS:

- No cambies el significado del contenido.
- No añadas explicaciones.
- No uses markdown.
- No uses bloques de código.
- Devuelve únicamente JSON válido.
- Corrige comillas, barras invertidas, comas,
  saltos de línea y cualquier error sintáctico.
- Todas las claves y valores de texto deben usar
  comillas dobles JSON válidas.

CONTENIDO A REPARAR:

{broken_text}
""".strip()

    payload = _call_gateway(
        prompt=repair_prompt,
        route="razonamiento",
    )

    repaired_text = payload.get("response", "")

    try:
        return _extract_json(repaired_text)
    except Exception as exc:
        raise ValueError(
            "La IA generó JSON inválido y el intento "
            f"automático de reparación también falló: {exc}"
        ) from exc


def _parse_protocol_json(
    raw_response: str,
) -> Dict[str, Any]:

    try:
        return _extract_json(raw_response)

    except Exception as first_error:

        log.warning(
            "JSON inicial inválido. Intentando reparación automática. "
            f"Error: {first_error}"
        )

        return _repair_json(raw_response)


def _validate_protocol(
    protocol: Dict[str, Any],
) -> Dict[str, Any]:

    expected_fields = [
        "suggested_title",
        "research_question",
        "framework",
        "population",
        "intervention",
        "comparator",
        "outcomes",
        "inclusion_criteria",
        "exclusion_criteria",
        "keywords",
        "pubmed_query",
    ]

    normalized = {}

    for field in expected_fields:

        value = protocol.get(field)

        if field == "keywords":

            if isinstance(value, list):
                normalized[field] = [
                    str(item).strip()
                    for item in value
                    if str(item).strip()
                ]

            elif isinstance(value, str):
                normalized[field] = [
                    item.strip()
                    for item in value.split(",")
                    if item.strip()
                ]

            else:
                normalized[field] = []

        else:
            normalized[field] = (
                str(value).strip()
                if value is not None
                else ""
            )

    if not normalized["suggested_title"]:
        raise ValueError(
            "La IA no generó un título propuesto"
        )

    if not normalized["research_question"]:
        raise ValueError(
            "La IA no generó una pregunta de investigación"
        )

    if not normalized["framework"]:
        normalized["framework"] = "PICO"

    return normalized


def _generate_protocol(
    topic: str,
    review_type: str,
) -> Dict[str, Any]:

    prompt = f"""
Actúa como metodólogo experto en revisiones sistemáticas,
PRISMA y búsqueda bibliográfica biomédica.

El investigador quiere diseñar una revisión sobre:

TEMA:
{topic}

TIPO DE REVISIÓN:
{review_type}

Tu tarea es proponer un protocolo inicial.

El protocolo será revisado y confirmado por una persona.
No tomes decisiones definitivas por el investigador.

Debes decidir el marco metodológico más apropiado:
PICO, PECO u otro equivalente.

Aunque recomiendes otro marco, devuelve siempre:
population, intervention, comparator y outcomes.

Genera:

1. Título científico.
2. Pregunta de investigación estructurada.
3. Framework recomendado.
4. Population.
5. Intervention / Exposure.
6. Comparator.
7. Outcomes.
8. Criterios de inclusión.
9. Criterios de exclusión.
10. Entre 6 y 15 palabras clave.
11. Estrategia inicial para PubMed.

REGLAS:

- No inventes resultados científicos.
- No inventes número de estudios.
- No afirmes que existe evidencia antes de buscarla.
- Los criterios deben ser utilizables en screening.
- Diferencia estudios primarios de revisiones secundarias.
- Usa términos MeSH solo si estás razonablemente seguro
  de que el descriptor existe.
- No uses términos MeSH traducidos al español.
- La consulta PubMed debe utilizar términos ingleses.
- No añadas [Title/Abstract] fuera de un término.
- No generes sintaxis PubMed innecesariamente compleja.
- No incluyas explicaciones fuera del JSON.
- Devuelve únicamente JSON válido.
- No uses markdown.

Devuelve exactamente estas claves:

{{
  "suggested_title": "",
  "research_question": "",
  "framework": "",
  "population": "",
  "intervention": "",
  "comparator": "",
  "outcomes": "",
  "inclusion_criteria": "",
  "exclusion_criteria": "",
  "keywords": [],
  "pubmed_query": ""
}}
""".strip()

    payload = _call_gateway(
        prompt=prompt,
        route="razonamiento",
    )

    raw_response = payload.get("response", "")

    protocol = _parse_protocol_json(
        raw_response
    )

    protocol = _validate_protocol(
        protocol
    )

    protocol["_model_used"] = payload.get(
        "_model_used"
    )

    protocol["_provider_used"] = payload.get(
        "_provider_used"
    )

    protocol["_task_type"] = payload.get(
        "_task_type"
    )

    return protocol


def handle(
    task_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:

    topic = (
        payload.get("topic")
        or payload.get("research_topic")
        or ""
    ).strip()

    review_type = (
        payload.get("review_type")
        or "systematic_review"
    ).strip()

    if not topic:
        raise ValueError(
            "topic es obligatorio"
        )

    try:
        set_status(
            task_id,
            "running",
            message="Diseñando protocolo con IA",
        )
    except Exception:
        pass

    try:

        protocol = _generate_protocol(
            topic=topic,
            review_type=review_type,
        )

        result = {
            "topic": topic,
            "review_type": review_type,
            "protocol": protocol,
        }

        try:
            set_status(
                task_id,
                "completed",
                result=result,
                message="Protocolo IA generado",
            )
        except Exception:
            pass

        log.info(
            "Protocolo IA generado correctamente",
            extra={"task_id": task_id},
        )

        return result

    except Exception as exc:

        log.exception(
            f"Error generando protocolo IA: {exc}",
            extra={"task_id": task_id},
        )

        try:
            set_status(
                task_id,
                "failed",
                error=str(exc),
                message="Error generando protocolo IA",
            )
        except Exception:
            pass

        raise
