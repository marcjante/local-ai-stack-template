"""Thesis ingestion orchestration referencing the shared document index."""

import hashlib
import logging
from pathlib import Path
import uuid

from psycopg2.extras import Json, RealDictCursor
from redis.exceptions import RedisError
from rq import Queue

from common import document_service as documents
from common.thesis_service import ThesisNotFound, _require_project, _profile
from db.db import get_conn, set_status
from workers.queue_conn import redis_conn, DEFAULT_RETRY

log = logging.getLogger(__name__)


def require_thesis(cur, project_id):
    _require_project(cur, project_id)
    _profile(cur, project_id)


def _fragments(cur, ingestion, doc):
    chunks = documents.chunks_for_document(cur, doc["doc_id"])
    metadata = doc.get("source_metadata") or {}
    for chunk in chunks:
        locator = dict(metadata.get("chunk_locators", {}).get(chunk["chunk_id"], {}))
        if chunk["page_number"] is not None:
            locator.setdefault("page_number", chunk["page_number"])
        if chunk["section"] is not None:
            locator.setdefault("section", chunk["section"])
        if not locator:
            locator["provenance"] = "legacy_available_metadata_only"
        chunk_field = "rag_chunk_id" if chunk["backend"] == "postgres_json" else "pgvector_chunk_id"
        cur.execute(
            f"INSERT INTO thesis_fragments (id, project_id, doc_id, {chunk_field}, file_type, "
            "source_role, source_locator, char_start, char_end, fragment_hash) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            f"ON CONFLICT (project_id, doc_id, {chunk_field}) DO NOTHING",
            (str(uuid.uuid4()), doc["project_id"], doc["doc_id"], chunk["chunk_id"],
             Path(doc.get("filename") or "").suffix.lower().lstrip(".") or "unknown",
             ingestion["source_role"], Json(locator), chunk["char_start"], chunk["char_end"],
             hashlib.sha256(chunk["text"].encode()).hexdigest()),
        )
    return len(chunks)


def _attach(cur, doc, role, reused, *, legacy_link=False):
    cur.execute(
        "INSERT INTO thesis_file_ingestions (id, project_id, doc_id, source_role, binary_identity, reused) "
        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (project_id,doc_id) DO NOTHING RETURNING id",
        (str(uuid.uuid4()), doc["project_id"], doc["doc_id"], role,
         "sha256_verified" if doc.get("content_hash") and doc.get("storage_key") else "legacy_unverified", reused),
    )
    created = cur.fetchone() is not None
    cur.execute("SELECT * FROM thesis_file_ingestions WHERE project_id=%s AND doc_id=%s FOR UPDATE",
                (doc["project_id"], doc["doc_id"]))
    ingestion = dict(cur.fetchone())
    if (legacy_link and not doc.get("storage_key")) or doc.get("extraction_status") == "indexed":
        count = _fragments(cur, ingestion, doc)
        cur.execute("UPDATE thesis_file_ingestions SET status='indexed', finished_at=now(), updated_at=now(), "
                    "warnings=%s WHERE id=%s", (Json([] if count else ["No hay chunks existentes que vincular"]), ingestion["id"]))
        ingestion["status"] = "indexed"
    return ingestion, created


def link_document(project_id, payload):
    if not isinstance(payload, dict) or set(payload) - {"doc_id", "source_role"}:
        raise ValueError("entrada de vinculación inválida")
    doc_id = payload.get("doc_id")
    if not isinstance(doc_id, str) or not doc_id.strip():
        raise ValueError("doc_id es obligatorio")
    role = documents.validate_role(payload.get("source_role", "unknown"))
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        require_thesis(cur, project_id)
        cur.execute("SELECT * FROM documents WHERE project_id=%s AND doc_id=%s FOR UPDATE", (project_id, doc_id))
        doc = cur.fetchone()
        if doc is None:
            raise ThesisNotFound("documento no encontrado en el proyecto")
        ingestion, created = _attach(cur, dict(doc), role, True, legacy_link=True)
    if ingestion["status"] in {"pending", "failed"}:
        enqueue_ingestion(project_id, ingestion["id"])
    return file_detail(project_id, ingestion["id"]), created


def upload_file(project_id, file, role):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        require_thesis(cur, project_id)
        doc, reused = documents.register_upload(conn, project_id, file, role=role, thesis_formats=True)
        ingestion, created = _attach(cur, doc, role, reused)
    if ingestion["status"] in {"pending", "failed"}:
        enqueue_ingestion(project_id, ingestion["id"])
    result = file_detail(project_id, ingestion["id"])
    result["reused"] = reused or not created
    return result


def enqueue_ingestion(project_id, file_id):
    """A committed pending/failed row is retryable by repeating the same upload."""
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM thesis_file_ingestions WHERE project_id=%s AND id=%s FOR UPDATE", (project_id, file_id))
        row = cur.fetchone()
        if row is None:
            raise ThesisNotFound("archivo no encontrado")
        if row["status"] not in {"pending", "failed"}:
            return
        task_id = str(uuid.uuid4())
        payload = {"project_id": project_id, "file_id": file_id}
        cur.execute("INSERT INTO tasks (id,project_id,queue,payload) VALUES (%s,%s,'thesis_ingest',%s)",
                    (task_id, project_id, Json(payload)))
        cur.execute("UPDATE thesis_file_ingestions SET job_id=%s,status='pending',error=NULL,updated_at=now() WHERE id=%s",
                    (task_id, file_id))
    try:
        Queue("thesis_ingest", connection=redis_conn).enqueue(
            "workers.plugins.thesis_ingest.handle", task_id, payload, job_id=task_id,
            retry=DEFAULT_RETRY, job_timeout=300,
        )
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE thesis_file_ingestions SET status='queued',updated_at=now() "
                        "WHERE project_id=%s AND id=%s AND job_id=%s AND status='pending'",
                        (project_id, file_id, task_id))
    except RedisError as exc:
        fail_ingestion(project_id, file_id, task_id, exc)
        # The failed row and stored original remain visible and can be retried.


def fail_ingestion(project_id, file_id, task_id, exc):
    log.exception("Thesis ingestion failed: %s", file_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE thesis_file_ingestions SET status='failed', error=%s, updated_at=now() "
                    "WHERE project_id=%s AND id=%s AND job_id=%s", (str(exc), project_id, file_id, task_id))
        cur.execute("UPDATE documents SET extraction_status='failed' WHERE project_id=%s AND doc_id="
                    "(SELECT doc_id FROM thesis_file_ingestions WHERE project_id=%s AND id=%s AND job_id=%s) "
                    "AND extraction_status IS DISTINCT FROM 'indexed'", (project_id, project_id, file_id, task_id))
    set_status(task_id, "failed", error=str(exc))


def extract_file(task_id, payload):
    project_id, file_id = payload["project_id"], payload["file_id"]
    try:
        with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            require_thesis(cur, project_id)
            cur.execute("SELECT * FROM thesis_file_ingestions WHERE project_id=%s AND id=%s", (project_id, file_id))
            ingestion = cur.fetchone()
            if ingestion is None:
                raise ThesisNotFound("archivo no encontrado")
            # Match upload/link lock order: document first, then ingestion.
            cur.execute("SELECT doc_id FROM documents WHERE project_id=%s AND doc_id=%s FOR UPDATE",
                        (project_id, ingestion["doc_id"]))
            cur.execute("SELECT * FROM thesis_file_ingestions WHERE project_id=%s AND id=%s FOR UPDATE", (project_id, file_id))
            ingestion = cur.fetchone()
            if ingestion["job_id"] != task_id:
                return {"status": "stale_job"}
            if ingestion["status"] == "indexed":
                return {"status": "indexed"}
            cur.execute("UPDATE thesis_file_ingestions SET status='extracting', started_at=now(), error=NULL WHERE id=%s", (file_id,))
            doc = documents.extract_document(conn, project_id, ingestion["doc_id"])
            count = _fragments(cur, dict(ingestion), doc)
            metadata = doc.get("source_metadata") or {}
            cur.execute("UPDATE thesis_file_ingestions SET status='indexed', parser=%s, parser_version=%s, "
                        "finished_at=now(), updated_at=now() WHERE id=%s",
                        (metadata.get("parser"), metadata.get("parser_version"), file_id))
            cur.execute("UPDATE tasks SET status='completed', result=%s, updated_at=now() WHERE id=%s AND project_id=%s",
                        (Json({"file_id": file_id, "fragment_count": count}), task_id, project_id))
        return {"status": "indexed", "fragment_count": count}
    except Exception as exc:
        # Record failure and re-raise so RQ retains traceback and applies its retry policy.
        fail_ingestion(project_id, file_id, task_id, exc)
        raise


def list_files(project_id):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        require_thesis(cur, project_id)
        cur.execute(
            "SELECT i.*, d.filename, d.content_type, d.content_hash, "
            "(d.storage_key IS NOT NULL) AS original_available, "
            "(SELECT count(*) FROM thesis_fragments f WHERE f.project_id=i.project_id AND f.doc_id=i.doc_id) AS fragment_count "
            "FROM thesis_file_ingestions i JOIN documents d ON d.project_id=i.project_id AND d.doc_id=i.doc_id "
            "WHERE i.project_id=%s ORDER BY i.created_at, i.id", (project_id,))
        return [dict(row) for row in cur.fetchall()]


def file_detail(project_id, file_id):
    files = list_files(project_id)
    result = next((f for f in files if f["id"] == file_id), None)
    if result is None:
        raise ThesisNotFound("archivo no encontrado en el proyecto")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM thesis_fragments WHERE project_id=%s AND doc_id=%s ORDER BY created_at,id", (project_id, result["doc_id"]))
        fragments = [dict(row) for row in cur.fetchall()]
        chunks = {(c["backend"], c["chunk_id"]): c for c in documents.chunks_for_document(cur, result["doc_id"])}
        for fragment in fragments:
            backend = "postgres_json" if fragment["rag_chunk_id"] else "pgvector"
            chunk = chunks[(backend, fragment["rag_chunk_id"] or fragment["pgvector_chunk_id"])]
            fragment["text"] = chunk["text"]
            fragment["position"] = chunk["position"]
        result["fragments"] = sorted(fragments, key=lambda f: (f["position"], f["id"]))
    result["file_id"] = result["id"]
    return result
