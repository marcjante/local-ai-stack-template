"""Generate and review project-scoped Thesis chapter placement suggestions."""

from collections import defaultdict
import uuid

from psycopg2.extras import RealDictCursor

from common.thesis_service import ThesisNotFound, _profile, _require_project
from db.db import get_conn

PLACER_VERSION = "rules-1"


def _targets(fragment):
    content_type = fragment.get("content_type") or "general_text"
    role = fragment.get("source_role") or "unknown"
    mapping = {
        "numeric_results": [("results", 0.94, "contiene cifras o estadísticos"), ("methods", 0.48, "puede describir variables o análisis")],
        "results_text": [("results", 0.90, "describe resultados explícitos"), ("discussion", 0.42, "podría contener interpretación")],
        "methodology": [("methods", 0.93, "describe metodología o participantes"), ("appendices", 0.38, "puede contener material metodológico complementario")],
        "scientific_context": [("background", 0.86, "aporta contexto científico"), ("introduction", 0.72, "puede apoyar la introducción")],
        "bibliography_entry": [("references", 0.98, "es una entrada bibliográfica")],
        "general_text": [("results", 0.55, "rol propio compatible con resultados") if role in {"own_data", "own_results"}
                          else ("background", 0.58, "rol compatible con antecedentes")],
    }
    return mapping.get(content_type, mapping["general_text"])


def generate_for_file(project_id, file_id):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _require_project(cur, project_id)
        _profile(cur, project_id)
        cur.execute("SELECT id, doc_id FROM thesis_file_ingestions WHERE project_id=%s AND id=%s", (project_id, file_id))
        ingestion = cur.fetchone()
        if ingestion is None:
            raise ThesisNotFound("archivo no encontrado en el proyecto")
        cur.execute("SELECT * FROM thesis_fragments WHERE project_id=%s AND doc_id=%s AND classification_status='classified' ORDER BY id", (project_id, ingestion["doc_id"]))
        fragments = cur.fetchall()
        cur.execute("SELECT id, chapter_type FROM thesis_chapters WHERE project_id=%s", (project_id,))
        chapters = {row["chapter_type"]: row["id"] for row in cur.fetchall()}
        created = 0
        for fragment in fragments:
            for chapter_type, confidence, reason in _targets(dict(fragment)):
                chapter_id = chapters.get(chapter_type)
                if not chapter_id:
                    continue
                cur.execute(
                    "INSERT INTO thesis_placement_suggestions "
                    "(id,project_id,fragment_id,chapter_id,confidence,reason,model,prompt_version) "
                    "VALUES (%s,%s,%s,%s,%s,%s,NULL,%s) ON CONFLICT (project_id,fragment_id,chapter_id) DO NOTHING",
                    (str(uuid.uuid4()), project_id, fragment["id"], chapter_id, confidence, reason, PLACER_VERSION),
                )
                created += cur.rowcount
        return {"file_id": file_id, "fragment_count": len(fragments), "suggestions_created": created, "placer_version": PLACER_VERSION}


def list_suggestions(project_id, status=None):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _require_project(cur, project_id)
        _profile(cur, project_id)
        params = [project_id]
        where = "WHERE s.project_id=%s"
        if status:
            if status not in {"pending", "approved", "corrected", "rejected"}:
                raise ValueError("status no permitido")
            where += " AND s.status=%s"
            params.append(status)
        cur.execute(
            "SELECT s.*, c.code AS chapter_code, c.title AS chapter_title, f.content_type, f.source_role, "
            "f.source_locator, f.doc_id FROM thesis_placement_suggestions s "
            "JOIN thesis_chapters c ON c.project_id=s.project_id AND c.id=s.chapter_id "
            "JOIN thesis_fragments f ON f.project_id=s.project_id AND f.id=s.fragment_id "
            + where + " ORDER BY s.created_at, s.id", params)
        return [dict(row) for row in cur.fetchall()]


def review_suggestion(project_id, suggestion_id, payload, reviewer_id):
    if not isinstance(payload, dict) or set(payload) - {"status", "corrected_chapter_id"}:
        raise ValueError("entrada de revisión inválida")
    status = payload.get("status")
    if status not in {"approved", "corrected", "rejected"}:
        raise ValueError("status debe ser approved, corrected o rejected")
    corrected = payload.get("corrected_chapter_id")
    if status == "corrected" and not isinstance(corrected, str):
        raise ValueError("corrected_chapter_id es obligatorio al corregir")
    if status != "corrected" and corrected is not None:
        raise ValueError("corrected_chapter_id solo se usa con corrected")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _require_project(cur, project_id)
        _profile(cur, project_id)
        cur.execute("SELECT * FROM thesis_placement_suggestions WHERE project_id=%s AND id=%s FOR UPDATE", (project_id, suggestion_id))
        suggestion = cur.fetchone()
        if suggestion is None:
            raise ThesisNotFound("propuesta no encontrada")
        if corrected:
            cur.execute("SELECT id FROM thesis_chapters WHERE project_id=%s AND id=%s", (project_id, corrected))
            if cur.fetchone() is None:
                raise ThesisNotFound("capítulo corregido no encontrado en el proyecto")
        cur.execute(
            "UPDATE thesis_placement_suggestions SET status=%s, corrected_chapter_id=%s, reviewer_id=%s, "
            "reviewed_at=now(), updated_at=now() WHERE project_id=%s AND id=%s RETURNING *",
            (status, corrected, reviewer_id or "unknown", project_id, suggestion_id),
        )
        return dict(cur.fetchone())
