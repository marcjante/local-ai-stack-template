"""Deterministic overlap warnings against the project's own Thesis sources."""

import re
import uuid
from difflib import SequenceMatcher
from psycopg2.extras import Json, RealDictCursor

from common.thesis_service import ThesisNotFound, _require_project
from db.db import get_conn


def _score(left, right):
    words_left = set(re.findall(r"[\wáéíóúñü]{4,}", left.casefold()))
    words_right = set(re.findall(r"[\wáéíóúñü]{4,}", right.casefold()))
    lexical = len(words_left & words_right) / len(words_left) if words_left else 0.0
    sequence = SequenceMatcher(None, left.casefold(), right.casefold()).ratio()
    return round(max(lexical, sequence), 4)


def check_version(project_id, version_id, checked_by=None):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _require_project(cur, project_id)
        cur.execute("SELECT content_markdown FROM thesis_section_versions WHERE project_id=%s AND id=%s", (project_id, version_id))
        version = cur.fetchone()
        if not version:
            raise ThesisNotFound("versión no encontrada")
        cur.execute("SELECT f.id, f.doc_id, f.source_locator, r.text FROM thesis_fragments f JOIN rag_chunks r ON r.chunk_id=f.rag_chunk_id WHERE f.project_id=%s AND f.rag_chunk_id IS NOT NULL", (project_id,))
        rows = list(cur.fetchall())
        cur.execute("SELECT to_regclass('public.rag_chunks_pgvector')")
        if cur.fetchone()["to_regclass"]:
            cur.execute("SELECT f.id, f.doc_id, f.source_locator, r.text FROM thesis_fragments f JOIN rag_chunks_pgvector r ON r.chunk_id=f.pgvector_chunk_id WHERE f.project_id=%s AND f.pgvector_chunk_id IS NOT NULL", (project_id,))
            rows.extend(cur.fetchall())
        matches = []
        for row in rows:
            score = _score(version["content_markdown"], row["text"])
            if score >= 0.25:
                matches.append({"fragment_id": row["id"], "doc_id": row["doc_id"], "score": score, "quote": row["text"][:300], "source_locator": row["source_locator"]})
        matches.sort(key=lambda item: item["score"], reverse=True)
        matches = matches[:20]
        max_score = matches[0]["score"] if matches else 0.0
        cur.execute("INSERT INTO thesis_overlap_checks (id,project_id,version_id,status,max_score,matches,checked_by) VALUES (%s,%s,%s,'completed',%s,%s,%s) ON CONFLICT (project_id,version_id) DO UPDATE SET status='completed', max_score=EXCLUDED.max_score, matches=EXCLUDED.matches, checked_by=EXCLUDED.checked_by, created_at=now() RETURNING *", (str(uuid.uuid4()), project_id, version_id, max_score, Json(matches), checked_by))
        return dict(cur.fetchone())


def get_check(project_id, version_id):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _require_project(cur, project_id)
        cur.execute("SELECT * FROM thesis_overlap_checks WHERE project_id=%s AND version_id=%s", (project_id, version_id))
        row = cur.fetchone()
        return dict(row) if row else None
