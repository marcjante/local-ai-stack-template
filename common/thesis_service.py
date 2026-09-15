"""Project-scoped Thesis configuration; no ingestion or writing workflow yet."""

import uuid

from psycopg2.extras import RealDictCursor

from db.db import get_conn


INITIAL_CHAPTERS = (
    ("cover", "Portada"),
    ("abstracts", "Resúmenes"),
    ("keywords", "Palabras clave"),
    ("indexes", "Índices"),
    ("introduction", "Introducción y justificación"),
    ("background", "Marco teórico y antecedentes"),
    ("objectives", "Hipótesis y objetivos"),
    ("methods", "Metodología"),
    ("results", "Resultados"),
    ("discussion", "Discusión"),
    ("limitations", "Limitaciones"),
    ("implications", "Implicaciones"),
    ("conclusions", "Conclusiones"),
    ("references", "Bibliografía"),
    ("acknowledgements", "Agradecimientos"),
    ("appendices", "Anexos"),
)
PROFILE_FIELDS = frozenset({
    "title", "author", "supervisors", "university", "program", "language",
    "citation_style", "template",
})


class ThesisNotFound(LookupError):
    """The project or requested Thesis resource does not exist."""


def validate_profile(payload):
    if not isinstance(payload, dict):
        raise ValueError("el perfil debe ser un objeto JSON")
    if payload.keys() - PROFILE_FIELDS:
        raise ValueError("campos de perfil desconocidos: " + ", ".join(sorted(payload.keys() - PROFILE_FIELDS)))
    for name, value in payload.items():
        if value is None and name not in {"title", "language"}:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{name} debe ser texto")
        if name == "language" and not value.strip():
            raise ValueError("language no puede estar vacío")
    return dict(payload)


def _require_project(cur, project_id):
    cur.execute("SELECT id FROM projects WHERE id = %s FOR KEY SHARE", (project_id,))
    if cur.fetchone() is None:
        raise ThesisNotFound("proyecto no encontrado")


def _profile(cur, project_id):
    cur.execute("SELECT * FROM thesis_profiles WHERE project_id = %s", (project_id,))
    row = cur.fetchone()
    if row is None:
        raise ThesisNotFound("tesis no encontrada")
    return dict(row)


def _update_profile(cur, project_id, values):
    if values:
        # Column names come exclusively from validate_profile's allowlist.
        assignments = ", ".join(f"{name} = %s" for name in values)
        cur.execute(
            f"UPDATE thesis_profiles SET {assignments}, updated_at = now() WHERE project_id = %s",
            (*values.values(), project_id),
        )


def create_thesis(project_id, payload):
    """Commit profile + 16 chapters together; retries preserve all existing edits."""
    values = validate_profile(payload)
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _require_project(cur, project_id)
        cur.execute(
            "INSERT INTO thesis_profiles (id, project_id) VALUES (%s, %s) "
            "ON CONFLICT (project_id) DO NOTHING RETURNING id",
            (str(uuid.uuid4()), project_id),
        )
        created = cur.fetchone() is not None
        if created:
            _update_profile(cur, project_id, values)
            for order, (chapter_type, title) in enumerate(INITIAL_CHAPTERS, 1):
                cur.execute(
                    "INSERT INTO thesis_chapters "
                    "(id, project_id, code, title, chapter_type, order_index) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (str(uuid.uuid4()), project_id, chapter_type, title, chapter_type, order),
                )
        return _profile(cur, project_id), created


def update_profile(project_id, payload):
    values = validate_profile(payload)
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _require_project(cur, project_id)
        _profile(cur, project_id)
        _update_profile(cur, project_id, values)
        return _profile(cur, project_id)


def get_structure(project_id):
    """Return a flat ordered tree; parent_id links sections to their parent."""
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _require_project(cur, project_id)
        profile = _profile(cur, project_id)
        cur.execute(
            "WITH RECURSIVE tree AS ("
            " SELECT c.*, ARRAY[c.order_index] AS sort_path, ARRAY[c.code] AS code_path"
            " FROM thesis_chapters c WHERE c.project_id = %s AND c.parent_id IS NULL"
            " UNION ALL"
            " SELECT c.*, t.sort_path || c.order_index, t.code_path || c.code"
            " FROM thesis_chapters c JOIN tree t ON c.parent_id = t.id"
            " AND c.project_id = t.project_id WHERE c.project_id = %s"
            ") SELECT * FROM tree ORDER BY sort_path, code_path, id",
            (project_id, project_id),
        )
        chapters = []
        for row in cur.fetchall():
            chapter = dict(row)
            chapter.pop("sort_path")
            chapter.pop("code_path")
            chapters.append(chapter)
        return {"project_id": project_id, "profile": profile, "chapters": chapters}


def update_chapter_title(project_id, chapter_id, title):
    """Rename independently of chapter_type; no sequential editing locks."""
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title debe ser texto no vacío")
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        _require_project(cur, project_id)
        cur.execute(
            "UPDATE thesis_chapters SET title = %s, updated_at = now() "
            "WHERE project_id = %s AND id = %s RETURNING *",
            (title, project_id, chapter_id),
        )
        row = cur.fetchone()
        if row is None:
            raise ThesisNotFound("capítulo no encontrado")
        return dict(row)
