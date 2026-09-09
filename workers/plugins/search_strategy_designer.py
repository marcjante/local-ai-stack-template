"""
Search Strategy Designer v3

Diseña y valida estrategias PubMed para revisiones sistemáticas.

Arquitectura:
1. El LLM propone conceptos y sinónimos.
2. Python normaliza y filtra los términos.
3. Python construye la sintaxis PubMed.
4. Python valida sintaxis básica.
5. PubMed valida la consulta real.
6. No se importan artículos automáticamente.
7. Siempre requiere confirmación humana.
"""

import json
import os
import re
from typing import Any, Dict, List, Tuple

import requests

from common.logging_setup import get_logger
from db.db import set_status


QUEUE_NAME = "search_strategy_designer"
QUEUE_TIMEOUT = 300

GATEWAY_URL = os.getenv(
    "LLM_GATEWAY_URL",
    "http://127.0.0.1:8091",
)

PUBMED_SEARCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/"
    "entrez/eutils/esearch.fcgi"
)

log = get_logger(__name__)


# -------------------------------------------------------------------
# JSON / LLM
# -------------------------------------------------------------------

def _extract_json(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError(
            "La IA devolvió una respuesta vacía."
        )

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

    if start == -1 or end <= start:
        raise ValueError(
            "La IA no devolvió JSON reconocible."
        )

    return json.loads(
        cleaned[start:end + 1]
    )


def _repair_json(
    broken_text: str,
) -> Dict[str, Any]:

    prompt = f"""
El siguiente texto debía ser JSON válido
pero contiene errores de sintaxis.

Corrígelo.

REGLAS:
- No añadas explicaciones.
- No uses markdown.
- No cambies el significado.
- Devuelve únicamente JSON válido.

TEXTO:

{broken_text}
""".strip()

    response = requests.post(
        f"{GATEWAY_URL}/generate",
        json={
            "prompt": prompt,
            "route": "razonamiento",
        },
        timeout=240,
    )

    if not response.ok:
        raise RuntimeError(
            f"Gateway HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    payload = response.json()

    repaired = payload.get(
        "response",
        "",
    )

    return _extract_json(repaired)


def _call_ai(
    prompt: str,
    skill_task: str = None,
) -> Dict[str, Any]:

    request_payload = {
        "prompt": prompt,
        "route": "razonamiento",
    }

    if skill_task:
        request_payload["skill_task"] = skill_task

    response = requests.post(
        f"{GATEWAY_URL}/generate",
        json=request_payload,
        timeout=240,
    )

    if not response.ok:
        raise RuntimeError(
            f"Gateway HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    payload = response.json()

    raw = payload.get(
        "response",
        "",
    )

    try:
        result = _extract_json(raw)

    except Exception:

        log.warning(
            "JSON del LLM inválido. "
            "Intentando reparación."
        )

        result = _repair_json(raw)

    result["_model_used"] = payload.get(
        "_model_used"
    )

    result["_provider_used"] = payload.get(
        "_provider_used"
    )

    result["_skill_task"] = payload.get(
        "_skill_task"
    )

    result["_skills_used"] = payload.get(
        "_skills_used",
        [],
    )

    return result


# -------------------------------------------------------------------
# Normalización
# -------------------------------------------------------------------

def _normalize_terms(
    terms: Any,
) -> List[str]:

    if not isinstance(terms, list):
        return []

    clean = []
    seen = set()

    for item in terms:

        value = str(item).strip()

        if not value:
            continue

        value = value.strip('"').strip()

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        key = value.lower()

        if key in seen:
            continue

        seen.add(key)
        clean.append(value)

    return clean


# -------------------------------------------------------------------
# Control metodológico
# -------------------------------------------------------------------

AI_MARKERS = (
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "neural network",
    "convolutional neural",
    "computer vision",
    "image recognition",
    "image classification",
    "image segmentation",
    "automated image analysis",
    "artificial neural",
    "deep neural",
    "ai-based",
    "ai based",
    "computer-aided",
    "computer aided",
)

WOUND_MARKERS = (
    "wound",
    "ulcer",
    "pressure injury",
    "pressure injuries",
    "pressure sore",
    "pressure sores",
    "diabetic foot",
    "venous leg",
    "arterial ulcer",
    "leg ulcer",
    "chronic wound",
    "non-healing",
    "nonhealing",
)

GENERIC_INTERVENTION_TERMS = {
    "wound assessment",
    "wound evaluation",
    "clinical examination",
    "diagnostic algorithms",
    "diagnostic algorithm",
    "image analysis",
    "diagnostic accuracy",
    "assessment",
    "evaluation",
}

OVERBROAD_POPULATION_TERMS = {
    "wound healing",
    "wounds",
    "injuries",
    "skin wounds",
}


def _is_valid_intervention_term(
    term: str,
) -> bool:

    value = term.lower().strip()

    if value in GENERIC_INTERVENTION_TERMS:
        return False

    return any(
        marker in value
        for marker in AI_MARKERS
    )


def _is_valid_population_term(
    term: str,
) -> bool:

    value = term.lower().strip()

    if value in OVERBROAD_POPULATION_TERMS:
        return False

    return any(
        marker in value
        for marker in WOUND_MARKERS
    )


def _filter_concept_terms(
    concept_name: str,
    free_terms: List[str],
) -> Tuple[List[str], List[str]]:

    name = concept_name.lower()

    kept = []
    removed = []

    for term in free_terms:

        keep = True

        if (
            "intervention" in name
            or "exposure" in name
        ):
            keep = _is_valid_intervention_term(
                term
            )

        elif "population" in name:
            keep = _is_valid_population_term(
                term
            )

        if keep:
            kept.append(term)
        else:
            removed.append(term)

    return kept, removed


def _safe_mesh_terms(
    concept_name: str,
    mesh_terms: List[str],
) -> Tuple[List[str], List[str]]:

    """
    Aplicamos una política conservadora:
    el LLM puede proponer MeSH, pero eliminamos
    términos demasiado amplios en población.
    """

    name = concept_name.lower()

    kept = []
    removed = []

    for term in mesh_terms:

        value = term.lower().strip()

        if "population" in name:

            if value in {
                "wounds and injuries",
                "wound healing",
            }:
                removed.append(term)
                continue

        kept.append(term)

    return kept, removed


# -------------------------------------------------------------------
# Constructor PubMed
# -------------------------------------------------------------------

def _escape_pubmed_term(
    term: str,
) -> str:

    return term.replace(
        '"',
        '\\"',
    )


def _build_free_text_block(
    terms: List[str],
) -> str:

    parts = []

    for term in terms:

        escaped = _escape_pubmed_term(
            term
        )

        parts.append(
            f'"{escaped}"[Title/Abstract]'
        )

    if not parts:
        return ""

    return (
        "("
        + " OR ".join(parts)
        + ")"
    )


def _build_mesh_block(
    terms: List[str],
) -> str:

    parts = []

    for term in terms:

        escaped = _escape_pubmed_term(
            term
        )

        parts.append(
            f'"{escaped}"[MeSH Terms]'
        )

    if not parts:
        return ""

    return (
        "("
        + " OR ".join(parts)
        + ")"
    )


def _build_concept_block(
    free_terms: List[str],
    mesh_terms: List[str],
) -> str:

    blocks = []

    free_block = _build_free_text_block(
        free_terms
    )

    mesh_block = _build_mesh_block(
        mesh_terms
    )

    if free_block:
        blocks.append(free_block)

    if mesh_block:
        blocks.append(mesh_block)

    if not blocks:
        return ""

    if len(blocks) == 1:
        return blocks[0]

    return (
        "("
        + " OR ".join(blocks)
        + ")"
    )


def _build_pubmed_query(
    concepts: List[Dict[str, Any]],
) -> Dict[str, Any]:

    blocks = []
    used_concepts = []
    removed_terms = []

    for concept in concepts:

        name = str(
            concept.get(
                "concept",
                "",
            )
        ).strip()

        include_in_query = bool(
            concept.get(
                "include_in_query",
                True,
            )
        )

        if not include_in_query:
            continue

        free_terms = _normalize_terms(
            concept.get(
                "free_text_terms"
            )
        )

        mesh_terms = _normalize_terms(
            concept.get(
                "mesh_terms"
            )
        )

        filtered_free, removed_free = (
            _filter_concept_terms(
                name,
                free_terms,
            )
        )

        filtered_mesh, removed_mesh = (
            _safe_mesh_terms(
                name,
                mesh_terms,
            )
        )

        for item in removed_free:
            removed_terms.append({
                "concept": name,
                "term": item,
                "type": "free_text",
                "reason":
                    "Término demasiado genérico "
                    "o no perteneciente al concepto.",
            })

        for item in removed_mesh:
            removed_terms.append({
                "concept": name,
                "term": item,
                "type": "mesh",
                "reason":
                    "MeSH demasiado amplio para "
                    "la búsqueda planteada.",
            })

        block = _build_concept_block(
            free_terms=filtered_free,
            mesh_terms=filtered_mesh,
        )

        if not block:
            continue

        blocks.append(block)

        used_concepts.append({
            "concept": name,
            "free_text_terms":
                filtered_free,
            "mesh_terms":
                filtered_mesh,
        })

    query = " AND ".join(blocks)

    return {
        "query":
            query,

        "used_concepts":
            used_concepts,

        "removed_terms":
            removed_terms,
    }


# -------------------------------------------------------------------
# Validación local
# -------------------------------------------------------------------

def _local_validation(
    query: str,
) -> Dict[str, Any]:

    errors = []
    warnings = []

    if not query.strip():
        errors.append(
            "La consulta está vacía."
        )

    if (
        query.count("(")
        != query.count(")")
    ):
        errors.append(
            "Los paréntesis no están equilibrados."
        )

    if query.count('"') % 2 != 0:
        errors.append(
            "Las comillas dobles no están equilibradas."
        )

    if not re.search(
        r"\bAND\b",
        query,
        re.IGNORECASE,
    ):
        warnings.append(
            "La búsqueda utiliza un único "
            "bloque conceptual."
        )

    if "[Title/Abstract]" not in query:
        warnings.append(
            "No hay términos libres "
            "en Title/Abstract."
        )

    return {
        "valid":
            len(errors) == 0,

        "errors":
            errors,

        "warnings":
            warnings,
    }


# -------------------------------------------------------------------
# Validación real PubMed
# -------------------------------------------------------------------

def _test_pubmed(
    query: str,
) -> Dict[str, Any]:

    response = requests.get(
        PUBMED_SEARCH_URL,
        params={
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": 0,
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    esearch = data.get(
        "esearchresult",
        {},
    )

    error_list = (
        esearch.get("errorlist")
        or {}
    )

    warning_list = (
        esearch.get("warninglist")
        or {}
    )

    errors = []

    for value in error_list.values():

        if isinstance(value, list):

            errors.extend(
                str(x)
                for x in value
            )

        elif value:

            errors.append(
                str(value)
            )

    warnings = []

    for value in warning_list.values():

        if isinstance(value, list):

            warnings.extend(
                str(x)
                for x in value
            )

        elif value:

            warnings.append(
                str(value)
            )

    try:
        count = int(
            esearch.get(
                "count",
                0,
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        count = 0

    return {
        "accepted_by_pubmed":
            len(errors) == 0,

        "total_found":
            count,

        "errors":
            errors,

        "warnings":
            warnings,

        "query_translation":
            esearch.get(
                "querytranslation",
                "",
            ),
    }


# -------------------------------------------------------------------
# Diseño mediante IA
# -------------------------------------------------------------------

def _design_concepts(
    payload: Dict[str, Any],
) -> Dict[str, Any]:

    research_question = str(
        payload.get(
            "research_question",
            "",
        )
        or ""
    ).strip()

    population = str(
        payload.get(
            "population",
            "",
        )
        or ""
    ).strip()

    intervention = str(
        payload.get(
            "intervention",
            "",
        )
        or ""
    ).strip()

    comparator = str(
        payload.get(
            "comparator",
            "",
        )
        or ""
    ).strip()

    outcomes = str(
        payload.get(
            "outcomes",
            "",
        )
        or ""
    ).strip()

    prompt = f"""
Actúa como bibliotecario especializado en
revisiones sistemáticas biomédicas y PubMed.

NO escribas la query PubMed final.

Tu tarea es únicamente identificar
conceptos y sinónimos.

PREGUNTA:
{research_question}

POBLACIÓN:
{population}

INTERVENCIÓN / EXPOSICIÓN:
{intervention}

COMPARADOR:
{comparator}

OUTCOMES:
{outcomes}

OBJETIVO:
Crear una estrategia inicial SENSIBLE
y reproducible.

REGLAS METODOLÓGICAS:

1. Los términos deben estar en inglés.

2. Population y Intervention/Exposure
   son normalmente los bloques principales.

3. Comparator normalmente debe llevar:
   "include_in_query": false

4. Outcomes normalmente debe llevar:
   "include_in_query": false

5. Para Population:
   utiliza conceptos específicos relacionados
   con la población real de la pregunta.

6. Si la población son heridas crónicas,
   considera cuando sea pertinente:
   - chronic wound
   - chronic wounds
   - non-healing wound
   - pressure ulcer
   - pressure injury
   - diabetic foot ulcer
   - venous leg ulcer
   - arterial ulcer

7. NO utilices "wound healing" como sinónimo
   de población con heridas crónicas.

8. Para Intervention/Exposure:
   SOLO incluye términos que representen
   realmente inteligencia artificial,
   aprendizaje automático,
   deep learning, computer vision,
   redes neuronales o técnicas equivalentes.

9. NO uses como términos de IA:
   - wound assessment
   - wound evaluation
   - diagnostic accuracy
   - clinical examination
   - assessment
   - diagnostic algorithms
   salvo que el término contenga explícitamente
   una técnica de IA.

10. Propón entre 3 y 10 términos libres
    por concepto principal.

11. Los free_text_terms deben poder buscarse
    literalmente en Title/Abstract.

12. Propón MeSH únicamente cuando tengas
    alta confianza de que el descriptor existe.

13. Si dudas de un MeSH, no lo incluyas.

14. Evita MeSH excesivamente amplios.

15. No inventes resultados ni número
    de artículos.

16. No escribas sintaxis PubMed.

17. No uses markdown.

18. Devuelve únicamente JSON válido.

FORMATO EXACTO:

{{
  "concepts": [
    {{
      "concept": "Population",
      "include_in_query": true,
      "free_text_terms": [],
      "mesh_terms": []
    }},
    {{
      "concept": "Intervention",
      "include_in_query": true,
      "free_text_terms": [],
      "mesh_terms": []
    }},
    {{
      "concept": "Comparator",
      "include_in_query": false,
      "free_text_terms": [],
      "mesh_terms": []
    }},
    {{
      "concept": "Outcomes",
      "include_in_query": false,
      "free_text_terms": [],
      "mesh_terms": []
    }}
  ],
  "rationale": ""
}}
""".strip()

    result = _call_ai(
        prompt,
        skill_task="search_strategy",
    )

    raw_concepts = (
        result.get("concepts")
        or []
    )

    normalized = []

    for concept in raw_concepts:

        if not isinstance(
            concept,
            dict,
        ):
            continue

        normalized.append({
            "concept":
                str(
                    concept.get(
                        "concept",
                        "",
                    )
                ).strip(),

            "include_in_query":
                bool(
                    concept.get(
                        "include_in_query",
                        True,
                    )
                ),

            "free_text_terms":
                _normalize_terms(
                    concept.get(
                        "free_text_terms"
                    )
                ),

            "mesh_terms":
                _normalize_terms(
                    concept.get(
                        "mesh_terms"
                    )
                ),
        })

    return {
        "concepts":
            normalized,

        "rationale":
            str(
                result.get(
                    "rationale",
                    "",
                )
                or ""
            ),

        "_model_used":
            result.get(
                "_model_used"
            ),

        "_provider_used":
            result.get(
                "_provider_used"
            ),

        "_skill_task":
            result.get(
                "_skill_task"
            ),

        "_skills_used":
            result.get(
                "_skills_used",
                [],
            ),
    }


# -------------------------------------------------------------------
# Plugin
# -------------------------------------------------------------------

def handle(
    task_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:

    log.info(
        "Diseñando estrategia PubMed v3",
        extra={
            "task_id": task_id
        },
    )

    try:
        set_status(
            task_id,
            "running",
        )
    except Exception:
        pass

    try:
        design = _design_concepts(
            payload
        )

        built = _build_pubmed_query(
            design["concepts"]
        )

        query = built["query"]

        local = _local_validation(
            query
        )

        pubmed = None

        if local["valid"]:

            try:

                pubmed = _test_pubmed(
                    query
                )

            except Exception as exc:

                pubmed = {
                    "accepted_by_pubmed":
                        False,

                    "total_found":
                        None,

                    "errors": [
                        "No se pudo validar "
                        "contra PubMed: "
                        f"{exc}"
                    ],

                    "warnings":
                        [],

                    "query_translation":
                        "",
                }

        valid = (
            local["valid"]
            and pubmed is not None
            and pubmed.get(
                "accepted_by_pubmed",
                False,
            )
        )

        result = {
            "query":
                query,

            "valid":
                valid,

            "concepts":
                design["concepts"],

            "used_concepts":
                built["used_concepts"],

            "removed_terms":
                built["removed_terms"],

            "rationale":
                design["rationale"],

            "local_validation":
                local,

            "pubmed_validation":
                pubmed,

            "model":
                design.get(
                    "_model_used"
                ),

            "provider":
                design.get(
                    "_provider_used"
                ),

            "_skill_task":
                design.get(
                    "_skill_task"
                ),

            "_skills_used":
                design.get(
                    "_skills_used",
                    [],
                ),

            "requires_human_confirmation":
                True,
        }

        try:
            set_status(
                task_id,
                "completed",
                result=result,
            )
        except Exception:
            pass

        log.info(
            "Estrategia PubMed v3 terminada. "
            f"valid={valid}",
            extra={
                "task_id": task_id
            },
        )

        return result

    except Exception as exc:
        try:
            set_status(
                task_id,
                "failed",
                error=str(exc),
            )
        except Exception:
            pass

        log.exception(
            "Error diseñando estrategia PubMed v3",
            extra={
                "task_id": task_id
            },
        )

        raise
