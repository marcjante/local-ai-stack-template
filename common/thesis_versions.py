"""Project-scoped Thesis source and version persistence (Phase 3A)."""

import uuid
from psycopg2.extras import Json, RealDictCursor

from common.thesis_service import ThesisNotFound, _profile, _require_project
from db.db import get_conn

PURPOSES = {"data", "evidence", "method", "context", "appendix", "style_rule"}
CLAIM_TYPES = {"own_result", "literature", "interpretation", "limitation", "recommendation"}


def _chapter(cur, project_id, chapter_id):
    _require_project(cur, project_id)
    _profile(cur, project_id)
    cur.execute("SELECT * FROM thesis_chapters WHERE project_id=%s AND id=%s", (project_id, chapter_id))
    row = cur.fetchone()
    if row is None:
        raise ThesisNotFound("capítulo no encontrado")
    return row


def add_source(project_id, chapter_id, payload, approved_by=None):
    if not isinstance(payload, dict) or set(payload) - {"fragment_id", "purpose"}:
        raise ValueError("entrada de fuente inválida")
    fragment_id, purpose = payload.get("fragment_id"), payload.get("purpose")
    if not isinstance(fragment_id, str) or purpose not in PURPOSES:
        raise ValueError("fragment_id y purpose válidos son obligatorios")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _chapter(cur, project_id, chapter_id)
        cur.execute("SELECT id FROM thesis_fragments WHERE project_id=%s AND id=%s", (project_id, fragment_id))
        if cur.fetchone() is None:
            raise ThesisNotFound("fragmento no encontrado")
        cur.execute("INSERT INTO thesis_section_sources (id,project_id,chapter_id,fragment_id,purpose,approved_by,approved_at) VALUES (%s,%s,%s,%s,%s,%s,CASE WHEN %s IS NULL THEN NULL ELSE now() END) ON CONFLICT (project_id,chapter_id,fragment_id) DO UPDATE SET purpose=EXCLUDED.purpose, approved_by=EXCLUDED.approved_by, approved_at=EXCLUDED.approved_at, updated_at=now() RETURNING id", (str(uuid.uuid4()), project_id, chapter_id, fragment_id, purpose, approved_by, approved_by))
        source_id = cur.fetchone()["id"]
        cur.execute("SELECT s.*, f.doc_id, f.source_locator FROM thesis_section_sources s JOIN thesis_fragments f ON f.project_id=s.project_id AND f.id=s.fragment_id WHERE s.id=%s", (source_id,))
        return dict(cur.fetchone())


def list_sources(project_id, chapter_id):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _chapter(cur, project_id, chapter_id)
        cur.execute("SELECT s.*, f.doc_id, f.source_locator, f.rag_chunk_id, f.pgvector_chunk_id FROM thesis_section_sources s JOIN thesis_fragments f ON f.project_id=s.project_id AND f.id=s.fragment_id WHERE s.project_id=%s AND s.chapter_id=%s ORDER BY s.created_at,s.id", (project_id, chapter_id))
        return [dict(row) for row in cur.fetchall()]


def create_version(project_id, chapter_id, payload, created_by=None):
    if not isinstance(payload, dict) or set(payload) - {"content_markdown", "status", "instructions", "model", "provider"}:
        raise ValueError("entrada de versión inválida")
    content = payload.get("content_markdown", "")
    status = payload.get("status", "draft")
    if not isinstance(content, str) or status not in {"draft", "under_review", "approved"}:
        raise ValueError("content_markdown y status válidos son obligatorios")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _chapter(cur, project_id, chapter_id)
        cur.execute("SELECT id FROM thesis_chapters WHERE project_id=%s AND id=%s FOR UPDATE", (project_id, chapter_id))
        cur.execute("SELECT COALESCE(MAX(version_number),0)+1 AS next_number FROM thesis_section_versions WHERE project_id=%s AND chapter_id=%s", (project_id, chapter_id))
        number = cur.fetchone()["next_number"]
        cur.execute("INSERT INTO thesis_section_versions (id,project_id,chapter_id,version_number,content_markdown,status,instructions,model,provider,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *", (str(uuid.uuid4()), project_id, chapter_id, number, content, status, payload.get("instructions"), payload.get("model"), payload.get("provider"), created_by))
        return dict(cur.fetchone())


def list_versions(project_id, chapter_id):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _chapter(cur, project_id, chapter_id)
        cur.execute("SELECT * FROM thesis_section_versions WHERE project_id=%s AND chapter_id=%s ORDER BY version_number", (project_id, chapter_id))
        return [dict(row) for row in cur.fetchall()]


def create_claim(project_id, version_id, payload):
    if not isinstance(payload, dict) or set(payload) - {"claim_text", "claim_type"}:
        raise ValueError("entrada de afirmación inválida")
    text, claim_type = payload.get("claim_text"), payload.get("claim_type", "interpretation")
    if not isinstance(text, str) or not text.strip() or claim_type not in CLAIM_TYPES:
        raise ValueError("claim_text y claim_type válidos son obligatorios")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _require_project(cur, project_id)
        cur.execute("SELECT id FROM thesis_section_versions WHERE project_id=%s AND id=%s", (project_id, version_id))
        if cur.fetchone() is None:
            raise ThesisNotFound("versión no encontrada")
        cur.execute("INSERT INTO thesis_claims (id,project_id,section_version_id,claim_text,claim_type) VALUES (%s,%s,%s,%s,%s) RETURNING *", (str(uuid.uuid4()), project_id, version_id, text.strip(), claim_type))
        return dict(cur.fetchone())


def list_claims(project_id, version_id):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _require_project(cur, project_id)
        cur.execute("SELECT * FROM thesis_claims WHERE project_id=%s AND section_version_id=%s ORDER BY created_at,id", (project_id, version_id))
        return [dict(row) for row in cur.fetchall()]


def add_claim_source(project_id, claim_id, payload):
    if not isinstance(payload, dict) or set(payload) - {"fragment_id", "source_quote", "source_locator", "verification_result", "verification_score"}:
        raise ValueError("entrada de fuente de afirmación inválida")
    fragment_id = payload.get("fragment_id")
    if not isinstance(fragment_id, str):
        raise ValueError("fragment_id es obligatorio")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _require_project(cur, project_id)
        cur.execute("SELECT id FROM thesis_claims WHERE project_id=%s AND id=%s", (project_id, claim_id))
        if cur.fetchone() is None:
            raise ThesisNotFound("afirmación no encontrada")
        cur.execute("SELECT doc_id, source_locator FROM thesis_fragments WHERE project_id=%s AND id=%s", (project_id, fragment_id))
        fragment = cur.fetchone()
        if fragment is None:
            raise ThesisNotFound("fragmento no encontrado")
        cur.execute("INSERT INTO thesis_claim_sources (id,project_id,claim_id,fragment_id,document_id,source_quote,source_locator,verification_result,verification_score) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (project_id,claim_id,fragment_id) DO UPDATE SET source_quote=EXCLUDED.source_quote, source_locator=EXCLUDED.source_locator, verification_result=EXCLUDED.verification_result, verification_score=EXCLUDED.verification_score, updated_at=now() RETURNING *", (str(uuid.uuid4()), project_id, claim_id, fragment_id, fragment["doc_id"], payload.get("source_quote"), Json(payload.get("source_locator") or fragment["source_locator"]), payload.get("verification_result"), payload.get("verification_score")))
        return dict(cur.fetchone())
