"""Project-scoped, reproducible classification for Thesis fragments.

This phase records role/content type and rationale only. Chapter placement and
LLM-generated prose are deliberately separate phases.
"""

from collections import Counter
from datetime import datetime, timezone
import re
import uuid

from psycopg2.extras import Json, RealDictCursor
from rq import Queue
from redis.exceptions import RedisError

from common import document_service
from db.db import get_conn
from workers.queue_conn import DEFAULT_RETRY, redis_conn


CLASSIFIER_VERSION = "heuristic-1"


def classify_text(text, filename, declared_role="unknown"):
    """Return stable labels without inferring destinations or fabricating evidence."""
    if declared_role != "unknown":
        role, confidence, reason = declared_role, 1.0, "rol declarado por el usuario"
    else:
        lowered = f"{filename} {text}".casefold()
        rules = (
            ("bibliography", ("bibtex", "references", "referencias", "bibliography", ".bib", ".ris"), 0.86),
            ("study_protocol", ("protocol", "protocolo", "ceic", "ethics", "ética", "methods", "metodología"), 0.80),
            ("administrative", ("consent", "consentimiento", "approval", "dictamen", "administrative"), 0.78),
            ("writing_guideline", ("guideline", "normativa", "style guide", "formatting", "universidad"), 0.78),
            ("scientific_evidence", ("abstract", "journal", "doi", "systematic review", "randomized"), 0.76),
            ("own_results", ("results", "resultados", "p-value", "p-valor", "confidence interval", "statistic"), 0.75),
            ("own_data", (".csv", ".xlsx", "participant", "patient", "variable", "dataset"), 0.72),
            ("draft", ("draft", "borrador", "chapter", "capítulo", "notes", "notas"), 0.68),
        )
        role, confidence, reason = "unknown", 0.35, "no se encontró una señal suficiente"
        for candidate, terms, score in rules:
            matched = [term for term in terms if term in lowered]
            if matched:
                role, confidence = candidate, score
                reason = "señales detectadas: " + ", ".join(matched[:3])
                break

    lowered = text.casefold()
    if re.search(r"p[- ]?valor|p-value|confidence interval|intervalo de confianza|\bmean\b|media", lowered):
        content_type = "numeric_results"
    elif any(term in lowered for term in ("methods", "metodología", "protocolo", "participants", "participantes")):
        content_type = "methodology"
    elif any(term in lowered for term in ("results", "resultados", "hallazgos")):
        content_type = "results_text"
    elif any(term in lowered for term in ("references", "referencias", "doi:", "bibliography")):
        content_type = "bibliography_entry"
    elif any(term in lowered for term in ("introduction", "introducción", "background", "antecedentes", "abstract")):
        content_type = "scientific_context"
    else:
        content_type = "general_text"
    return {"source_role": role, "content_type": content_type,
            "confidence": confidence, "reason": reason, "version": CLASSIFIER_VERSION}


def classify_file(project_id, file_id):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT i.id, i.doc_id, i.source_role, d.filename "
            "FROM thesis_file_ingestions i JOIN documents d ON d.project_id=i.project_id AND d.doc_id=i.doc_id "
            "WHERE i.project_id=%s AND i.id=%s FOR UPDATE", (project_id, file_id),
        )
        ingestion = cur.fetchone()
        if ingestion is None:
            raise ValueError("archivo no encontrado en el proyecto")
        cur.execute("SELECT * FROM thesis_fragments WHERE project_id=%s AND doc_id=%s FOR UPDATE",
                    (project_id, ingestion["doc_id"]))
        fragments = cur.fetchall()
        if not fragments:
            raise ValueError("el archivo no tiene fragmentos indexados")
        counts = Counter()
        for fragment in fragments:
            # The detail endpoint resolves chunk text; classify directly from RAG references here.
            if fragment["rag_chunk_id"]:
                cur.execute("SELECT text FROM rag_chunks WHERE chunk_id=%s AND doc_id=%s",
                            (fragment["rag_chunk_id"], fragment["doc_id"]))
            else:
                cur.execute("SELECT text FROM rag_chunks_pgvector WHERE chunk_id=%s AND doc_id=%s",
                            (fragment["pgvector_chunk_id"], fragment["doc_id"]))
            row = cur.fetchone()
            if row is None:
                raise ValueError("chunk de fragmento no encontrado")
            result = classify_text(row["text"], ingestion["filename"] or "", ingestion["source_role"])
            counts[result["source_role"]] += 1
            cur.execute(
                "UPDATE thesis_fragments SET source_role=%s, content_type=%s, classification_status='classified', "
                "classification_confidence=%s, classification_reason=%s, classifier_version=%s, classified_at=now() "
                "WHERE id=%s AND project_id=%s",
                (result["source_role"], result["content_type"], result["confidence"], result["reason"], result["version"], fragment["id"], project_id),
            )
        # Only promote an unknown document role when the classifier has a strong, consistent result.
        if ingestion["source_role"] == "unknown" and counts:
            role, count = counts.most_common(1)[0]
            if role != "unknown" and count / len(fragments) >= 0.5:
                cur.execute("UPDATE documents SET source_role=%s WHERE project_id=%s AND doc_id=%s AND (source_role IS NULL OR source_role='unknown')",
                            (role, project_id, ingestion["doc_id"]))
        return {"file_id": file_id, "fragment_count": len(fragments), "roles": dict(counts), "classifier_version": CLASSIFIER_VERSION}


def enqueue_classification(project_id, file_id, parent_job_id):
    task_id = str(uuid.uuid4())
    payload = {"project_id": project_id, "file_id": file_id}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO tasks (id, project_id, queue, payload) VALUES (%s,%s,'thesis_classify',%s)",
                    (task_id, project_id, Json(payload)))
    try:
        Queue("thesis_classify", connection=redis_conn).enqueue(
            "workers.plugins.thesis_classify.handle", task_id, payload,
            job_id=task_id, retry=DEFAULT_RETRY, job_timeout=300,
        )
    except RedisError:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE tasks SET status='failed', error='Redis no disponible', updated_at=now() WHERE id=%s", (task_id,))
    return task_id
