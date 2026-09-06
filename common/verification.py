"""
verification.py

Subagentes del "circuito de información veraz". Cada uno tiene una
responsabilidad única y deja su veredicto en audit_log vía db.log_audit().
Diseñados para poder llamarse en cadena desde cualquier worker, no solo
desde "process".

Son heurísticas simples a propósito (esto es una plantilla): sustitúyelas
por lo que necesite el proyecto real (un segundo LLM como juez, un
servicio de fact-checking externo, reglas de negocio concretas...).
"""

from db.db import log_audit


def cross_check_sources(task_id: str, claim: str, sources: list) -> dict:
    """
    Subagente 1: ¿cuántas fuentes independientes respaldan esta afirmación?
    `sources` es una lista de dicts con al menos {"id":..., "text":...}.

    Heurística mínima: cuenta en cuántas fuentes aparece literalmente el
    texto de `claim` (o una porción significativa). Un proyecto real
    debería usar similitud semántica, no coincidencia de texto.
    """
    claim_lower = claim.lower().strip()
    supporting = [s for s in sources if claim_lower and claim_lower in s.get("text", "").lower()]
    n_support = len(supporting)
    n_total = len(sources)

    confidence = (n_support / n_total) if n_total else 0.0
    if n_total == 0:
        verdict = "sin_fuentes"
    elif n_support >= 2:
        verdict = "corroborado"
    elif n_support == 1:
        verdict = "una_sola_fuente"
    else:
        verdict = "sin_respaldo"

    result = {
        "claim": claim,
        "n_sources_checked": n_total,
        "n_sources_supporting": n_support,
        "supporting_ids": [s.get("id") for s in supporting],
        "verdict": verdict,
        "confidence": confidence,
    }
    log_audit(task_id, step="cross_check", subagent="cross_check_sources",
              verdict=verdict, confidence=confidence, details=result)
    return result


def detect_hallucination(task_id: str, answer: str, sources: list) -> dict:
    """
    Subagente 2: ¿el texto generado por el LLM se apoya en las fuentes
    reales, o parece inventado?

    Heurística mínima: solapamiento de palabras significativas (>4
    letras) entre la respuesta y el conjunto de fuentes. Bajo solapamiento
    no demuestra que algo esté inventado, pero es una señal barata de
    alerta temprana — para verificación real, usa un LLM juez comparando
    afirmación por afirmación contra las fuentes, como hace TBC-IA.
    """
    def significant_words(text):
        return {w.lower() for w in text.split() if len(w) > 4}

    answer_words = significant_words(answer)
    source_words = set()
    for s in sources:
        source_words |= significant_words(s.get("text", ""))

    if not answer_words:
        overlap_ratio = 0.0
    else:
        overlap_ratio = len(answer_words & source_words) / len(answer_words)

    if overlap_ratio >= 0.5:
        verdict = "respaldado"
    elif overlap_ratio >= 0.2:
        verdict = "parcialmente_respaldado"
    else:
        verdict = "posible_alucinacion"

    result = {
        "overlap_ratio": round(overlap_ratio, 3),
        "verdict": verdict,
        "n_sources": len(sources),
    }
    log_audit(task_id, step="hallucination_check", subagent="detect_hallucination",
              verdict=verdict, confidence=overlap_ratio, details=result)
    return result
