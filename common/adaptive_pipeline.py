"""
adaptive_pipeline.py

En vez de ejecutar siempre los mismos subagentes en el mismo orden, este
módulo decide, según la tarea concreta, qué hace falta de verdad:

  - gather_candidate_chunks(): si el payload ya trae las fuentes, las usa
    directamente (troceo al vuelo, sin tocar el índice persistente); si
    trae un doc_id, busca solo dentro de ese documento ya indexado; si no
    trae nada, busca en todo el índice. Cada camino queda registrado en
    audit_log para que se vea por qué se tomó esa decisión.

  - decide_need_verification(): si no hay ninguna fuente candidata, no
    tiene sentido ejecutar el subagente de verificación por afirmaciones
    (no hay nada contra lo que citar) — se marca directamente como
    'sin_fuentes' sin gastar ciclos en partir la respuesta en frases y
    compararlas. Igual si la respuesta es trivial (muy corta).

Esto es lo que lo hace "adaptativo": el circuito no es una cadena fija de
5 pasos siempre — se salta trabajo cuando no aporta nada.
"""

from db.db import log_audit
from rag.chunking import split_into_chunks
from rag.embeddings import embed_text, cosine_similarity
from rag.retrieval import retrieve


def gather_candidate_chunks(task_id: str, payload: dict, query: str) -> tuple:
    """Devuelve (chunks, path_used) — path_used queda auditado."""
    provided_sources = payload.get("sources")
    doc_id = payload.get("doc_id")

    if provided_sources:
        # Las fuentes ya vienen en la petición: se trocean al vuelo, sin
        # tocar el índice persistente (más rápido, no hace falta indexar
        # algo que solo se usa una vez).
        chunks = []
        for src in provided_sources:
            chunks.extend(split_into_chunks(src.get("id", "fuente"), src.get("text", "")))
        query_emb = embed_text(query)
        for c in chunks:
            c["score"] = cosine_similarity(query_emb, embed_text(c["text"]))
        chunks.sort(key=lambda c: c["score"], reverse=True)
        path = "sources_directas"

    elif doc_id:
        # Documento concreto ya indexado antes (POST /rag/index): busca
        # solo dentro de él, no en todo el corpus.
        chunks = retrieve(query, top_k=10, doc_id=doc_id)
        path = "indice_doc_id"

    else:
        # Sin pistas: busca en todo lo indexado hasta ahora.
        chunks = retrieve(query, top_k=10)
        path = "indice_global"

    log_audit(task_id, step="gather", subagent="gather_candidate_chunks",
              verdict=path, details={"n_chunks": len(chunks), "path": path})
    return chunks, path


def decide_need_verification(task_id: str, answer: str, candidate_chunks: list) -> bool:
    """
    True si merece la pena ejecutar cross_check_sources; False si se puede
    saltar (y por qué, registrado en audit_log).
    """
    if not candidate_chunks:
        log_audit(task_id, step="decide_verification", subagent="decide_need_verification",
                  verdict="omitido_sin_fuentes", details={"reason": "no hay chunks candidatos"})
        return False

    if len(answer.split()) < 6:
        log_audit(task_id, step="decide_verification", subagent="decide_need_verification",
                  verdict="omitido_respuesta_trivial", details={"answer_words": len(answer.split())})
        return False

    log_audit(task_id, step="decide_verification", subagent="decide_need_verification",
              verdict="necesario", details={"n_chunks": len(candidate_chunks)})
    return True
