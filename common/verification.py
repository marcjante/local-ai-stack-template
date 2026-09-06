"""
verification.py

Subagentes del "circuito de información veraz", ahora a nivel de
AFIRMACIÓN, no de respuesta completa: cada frase de la respuesta del LLM
se comprueba por separado contra los chunks del RAG, exigiendo una cita
textual real — no basta con que "algo" de la respuesta se parezca a
"algo" de las fuentes.

Cada subagente deja su veredicto en audit_log vía db.log_audit().
"""

import re

from db.db import log_audit
from rag.rerank import rerank


def split_into_claims(answer: str) -> list:
    """Divide la respuesta en afirmaciones (frases) verificables por separado."""
    parts = re.split(r'(?<=[.!?])\s+', answer.strip())
    return [p.strip() for p in parts if len(p.strip()) > 8]


def _word_overlap(a: str, b: str) -> float:
    wa = set(re.findall(r"[a-záéíóúñü0-9]{4,}", a.lower()))
    wb = set(re.findall(r"[a-záéíóúñü0-9]{4,}", b.lower()))
    if not wa:
        return 0.0
    return len(wa & wb) / len(wa)


def verify_claim(claim: str, candidate_chunks: list, quote_threshold: float = 0.6) -> dict:
    """
    Subagente de una sola afirmación: busca, entre los chunks candidatos,
    el que mejor la respalda, y exige una cita textual real (no solo
    'se parece'): al menos `quote_threshold` de las palabras
    significativas de la afirmación deben aparecer en el chunk citado.
    """
    if not candidate_chunks:
        return {"claim": claim, "verdict": "sin_fuentes", "citation": None, "overlap": 0.0}

    ranked = rerank(claim, [dict(c) for c in candidate_chunks], top_n=1)
    best = ranked[0] if ranked else None
    if not best:
        return {"claim": claim, "verdict": "sin_fuentes", "citation": None, "overlap": 0.0}

    overlap = _word_overlap(claim, best.get("text", ""))
    if overlap >= quote_threshold:
        verdict = "citado"
    elif overlap >= 0.3:
        verdict = "parcial"
    else:
        verdict = "sin_respaldo"

    return {
        "claim": claim,
        "verdict": verdict,
        "overlap": round(overlap, 3),
        "citation": {
            "doc_id": best.get("doc_id"),
            "chunk_id": best.get("chunk_id"),
            "quote": best.get("text", "")[:300],
        } if verdict != "sin_respaldo" else None,
    }


def cross_check_sources(task_id: str, answer: str, candidate_chunks: list) -> dict:
    """
    Subagente agregador: parte la respuesta en afirmaciones, verifica cada
    una por separado contra los chunks del RAG, y da un veredicto conjunto
    con la lista de citas exactas — la base real de un "circuito veraz",
    en vez de una comparación de la respuesta entera contra todo el texto.
    """
    claims = split_into_claims(answer)
    per_claim = [verify_claim(c, candidate_chunks) for c in claims]

    n_total = len(per_claim)
    n_cited = sum(1 for c in per_claim if c["verdict"] == "citado")
    n_partial = sum(1 for c in per_claim if c["verdict"] == "parcial")
    n_unsupported = sum(1 for c in per_claim if c["verdict"] in ("sin_respaldo", "sin_fuentes"))

    confidence = (n_cited + 0.5 * n_partial) / n_total if n_total else 0.0

    if n_total == 0:
        verdict = "sin_afirmaciones"
    elif n_unsupported == 0:
        verdict = "todo_citado"
    elif n_cited + n_partial >= n_total * 0.5:
        verdict = "mayoria_citada"
    else:
        verdict = "mayoria_sin_citar"

    result = {
        "verdict": verdict,
        "confidence": round(confidence, 3),
        "n_claims": n_total,
        "n_cited": n_cited,
        "n_partial": n_partial,
        "n_unsupported": n_unsupported,
        "claims": per_claim,
    }
    log_audit(task_id, step="cross_check", subagent="cross_check_sources",
              verdict=verdict, confidence=confidence, details=result)
    return result
