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
