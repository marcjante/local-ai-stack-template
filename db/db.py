"""
db.py

Acceso mínimo a Postgres para el ciclo de vida de las tareas
(pending / running / completed / failed). Lo usan tanto el backend
(al encolar) como los workers (al procesar).

No es un ORM completo a propósito: para un proyecto real, sustitúyelo
por SQLAlchemy/asyncpg si crece la complejidad. Aquí se prioriza que
sea fácil de leer y de copiar a un proyecto nuevo.
"""

import os
import json
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

DB_DSN = os.environ.get(
    "DATABASE_URL",
    "dbname=stack_template user=postgres password=postgres host=127.0.0.1 port=5432",
)


@contextmanager
def get_conn():
    conn = psycopg2.connect(DB_DSN)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema():
    """
    Crea las tablas núcleo (tasks, audit_log, rag_chunks, n8n_integrations)
    si no existen. Se llaman siempre, sin depender de nada opcional.

    La parte de pgvector (schema_pgvector.sql) es aparte a propósito: el
    backend por defecto del RAG (RAG_BACKEND=postgres_json) no necesita
    la extensión `vector`, así que su ausencia no debe impedir arrancar
    el resto del proyecto. Si la extensión no está instalada en este
    Postgres, se avisa por stdout y se sigue — solo falla si luego
    alguien intenta usar RAG_BACKEND=pgvector de verdad sin haberla
    instalado.
    """
    with get_conn() as conn, conn.cursor() as cur:
        with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
            cur.execute(f.read())

    try:
        with get_conn() as conn, conn.cursor() as cur:
            with open(os.path.join(os.path.dirname(__file__), "schema_pgvector.sql")) as f:
                cur.execute(f.read())
    except Exception as e:
        print(f"[db.init_schema] pgvector no disponible, se omite (normal si usas el backend por defecto): {e}")


def create_task(task_id: str, queue: str, payload: dict, project_id: str = "default"):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tasks (id, queue, status, payload, attempts, project_id)
            VALUES (%s, %s, 'pending', %s, 0, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (task_id, queue, json.dumps(payload), project_id),
        )


def set_status(task_id: str, status: str, result: dict = None, error: str = None, increment_attempts: bool = False):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE tasks
            SET status = %s,
                result = %s,
                error = %s,
                updated_at = now()
                {", attempts = attempts + 1" if increment_attempts else ""}
            WHERE id = %s
            """,
            (status, json.dumps(result) if result is not None else None, error, task_id),
        )


def get_task(task_id: str):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
        return cur.fetchone()


def log_audit(task_id: str, step: str, subagent: str, verdict: str = None,
              confidence: float = None, details: dict = None):
    """
    Deja constancia de qué subagente actuó, qué decidió y con qué confianza.
    Es la base del 'circuito de información veraz': cualquier tarea se puede
    reconstruir paso a paso después, viendo qué comprobó cada subagente.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log (task_id, step, subagent, verdict, confidence, details)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (task_id, step, subagent, verdict, confidence, json.dumps(details) if details else None),
        )


def get_audit_trail(task_id: str):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM audit_log WHERE task_id = %s ORDER BY created_at", (task_id,))
        return cur.fetchall()


def is_integration_enabled(flow_name: str, project_id: str = "default") -> bool:
    """
    Comprueba si un flujo de n8n está activado PARA ESE PROYECTO. Si no
    existe todavía en la tabla, lo registra como activado por defecto
    (para no romper el comportamiento de quien no ha tocado nada) y
    devuelve True.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT enabled FROM n8n_integrations WHERE flow_name = %s AND project_id = %s",
                    (flow_name, project_id))
        row = cur.fetchone()
        if row is not None:
            return row[0]
        cur.execute(
            "INSERT INTO n8n_integrations (flow_name, project_id, enabled) VALUES (%s, %s, true) ON CONFLICT DO NOTHING",
            (flow_name, project_id),
        )
        return True


def set_integration_enabled(flow_name: str, enabled: bool, project_id: str = "default", description: str = None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO n8n_integrations (flow_name, project_id, enabled, description, updated_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (project_id, flow_name) DO UPDATE
            SET enabled = EXCLUDED.enabled, updated_at = now(),
                description = COALESCE(EXCLUDED.description, n8n_integrations.description)
            """,
            (flow_name, project_id, enabled, description),
        )


def list_integrations(project_id: str = "default"):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM n8n_integrations WHERE project_id = %s ORDER BY flow_name", (project_id,))
        return cur.fetchall()


def list_tasks(status: str = None, limit: int = 50, project_id: str = None):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        clauses, params = [], []
        if status:
            clauses.append("status = %s")
            params.append(status)
        if project_id:
            clauses.append("project_id = %s")
            params.append(project_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        cur.execute(f"SELECT * FROM tasks {where} ORDER BY created_at DESC LIMIT %s", params)
        return cur.fetchall()


def task_counts_by_status(project_id: str = None):
    with get_conn() as conn, conn.cursor() as cur:
        if project_id:
            cur.execute("SELECT status, count(*) FROM tasks WHERE project_id = %s GROUP BY status", (project_id,))
        else:
            cur.execute("SELECT status, count(*) FROM tasks GROUP BY status")
        return dict(cur.fetchall())


# --- Projects/Workspaces ---

def create_project(project_id: str, name: str, description: str = None, project_type: str = "blank"):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, description, project_type) VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description
            """,
            (project_id, name, description, project_type),
        )
        cur.execute("INSERT INTO project_settings (project_id) VALUES (%s) ON CONFLICT DO NOTHING", (project_id,))


def list_projects():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT p.*,
                   (SELECT count(*) FROM collections c WHERE c.project_id = p.id) as n_collections,
                   (SELECT count(*) FROM documents d WHERE d.project_id = p.id) as n_documents,
                   (SELECT count(*) FROM tasks t WHERE t.project_id = p.id) as n_tasks
            FROM projects p ORDER BY p.created_at
        """)
        return cur.fetchall()


def get_project(project_id: str):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
        return cur.fetchone()


def get_project_settings(project_id: str):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM project_settings WHERE project_id = %s", (project_id,))
        return cur.fetchone()


def update_project_settings(project_id: str, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k} = %s" for k in fields)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE project_settings SET {cols}, updated_at = now() WHERE project_id = %s",
            (*fields.values(), project_id),
        )


def project_recent_errors(project_id: str, limit: int = 5):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id, queue, error, updated_at FROM tasks WHERE project_id = %s AND status = 'failed' "
            "ORDER BY updated_at DESC LIMIT %s",
            (project_id, limit),
        )
        return cur.fetchall()


# --- Colecciones y documentos (Knowledge) ---

def create_collection(collection_id: str, name: str, project_id: str = "default", description: str = None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO collections (id, project_id, name, description) VALUES (%s, %s, %s, %s)
            ON CONFLICT (project_id, id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description
            """,
            (collection_id, project_id, name, description),
        )


def list_collections(project_id: str = "default"):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT c.*, count(d.doc_id) as n_documents
            FROM collections c LEFT JOIN documents d ON d.collection_id = c.id AND d.project_id = c.project_id
            WHERE c.project_id = %s
            GROUP BY c.project_id, c.id ORDER BY c.created_at
        """, (project_id,))
        return cur.fetchall()


def ensure_default_collection(project_id: str = "default"):
    """La colección 'default' siempre existe en cada proyecto, para no obligar a crear una antes de poder subir nada."""
    create_collection("default", "Default", project_id=project_id, description="Colección por defecto")


def register_document(doc_id: str, collection_id: str, filename: str, content_type: str,
                       doc_version: str, embedding_model: str, raw_text: str, n_chunks: int,
                       project_id: str = "default"):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (doc_id, collection_id, project_id, filename, content_type, doc_version,
                                    embedding_model, raw_text, n_chunks, indexed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (doc_id) DO UPDATE SET
                collection_id = EXCLUDED.collection_id, project_id = EXCLUDED.project_id,
                filename = EXCLUDED.filename, content_type = EXCLUDED.content_type,
                doc_version = EXCLUDED.doc_version, embedding_model = EXCLUDED.embedding_model,
                raw_text = EXCLUDED.raw_text, n_chunks = EXCLUDED.n_chunks, indexed_at = now()
            """,
            (doc_id, collection_id, project_id, filename, content_type, doc_version, embedding_model, raw_text, n_chunks),
        )


def list_documents(collection_id: str = None, project_id: str = "default"):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        if collection_id:
            cur.execute("SELECT doc_id, filename, content_type, doc_version, embedding_model, n_chunks, indexed_at "
                        "FROM documents WHERE collection_id = %s AND project_id = %s ORDER BY indexed_at DESC",
                        (collection_id, project_id))
        else:
            cur.execute("SELECT doc_id, collection_id, filename, content_type, doc_version, embedding_model, n_chunks, indexed_at "
                        "FROM documents WHERE project_id = %s ORDER BY indexed_at DESC", (project_id,))
        return cur.fetchall()


def get_document(doc_id: str):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM documents WHERE doc_id = %s", (doc_id,))
        return cur.fetchone()


def delete_document(doc_id: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM rag_chunks WHERE doc_id = %s", (doc_id,))
        cur.execute("SELECT to_regclass('public.rag_chunks_pgvector')")
        if cur.fetchone()[0] is not None:
            cur.execute("DELETE FROM rag_chunks_pgvector WHERE doc_id = %s", (doc_id,))
        cur.execute("DELETE FROM documents WHERE doc_id = %s", (doc_id,))


def get_document_chunks(doc_id: str):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT chunk_id, position, text FROM rag_chunks WHERE doc_id = %s ORDER BY position", (doc_id,))
        return cur.fetchall()
