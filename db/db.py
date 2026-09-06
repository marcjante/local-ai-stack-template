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
    """Crea la tabla tasks si no existe. Llamar una vez al arrancar el backend."""
    with get_conn() as conn, conn.cursor() as cur:
        with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
            cur.execute(f.read())


def create_task(task_id: str, queue: str, payload: dict):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tasks (id, queue, status, payload, attempts)
            VALUES (%s, %s, 'pending', %s, 0)
            ON CONFLICT (id) DO NOTHING
            """,
            (task_id, queue, json.dumps(payload)),
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


def is_integration_enabled(flow_name: str) -> bool:
    """
    Comprueba si un flujo de n8n está activado. Si no existe todavía en
    la tabla, lo registra como activado por defecto (para no romper el
    comportamiento de quien no ha tocado nada) y devuelve True.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT enabled FROM n8n_integrations WHERE flow_name = %s", (flow_name,))
        row = cur.fetchone()
        if row is not None:
            return row[0]
        cur.execute(
            "INSERT INTO n8n_integrations (flow_name, enabled) VALUES (%s, true) ON CONFLICT DO NOTHING",
            (flow_name,),
        )
        return True


def set_integration_enabled(flow_name: str, enabled: bool, description: str = None):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO n8n_integrations (flow_name, enabled, description, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (flow_name) DO UPDATE
            SET enabled = EXCLUDED.enabled, updated_at = now(),
                description = COALESCE(EXCLUDED.description, n8n_integrations.description)
            """,
            (flow_name, enabled, description),
        )


def list_integrations():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM n8n_integrations ORDER BY flow_name")
        return cur.fetchall()


def list_tasks(status: str = None, limit: int = 50):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        if status:
            cur.execute(
                "SELECT * FROM tasks WHERE status = %s ORDER BY created_at DESC LIMIT %s",
                (status, limit),
            )
        else:
            cur.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT %s", (limit,))
        return cur.fetchall()


def task_counts_by_status():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, count(*) FROM tasks GROUP BY status")
        return dict(cur.fetchall())
