"""baseline

Revision ID: 2a9187c48a69
Revises:
Create Date: 2026-09-07 11:48:46.198720

Migración base: crea el esquema núcleo completo tal como estaba antes
de adoptar Alembic (ver db/schema.sql, que sigue siendo la referencia
legible de lo que hay). A partir de aquí, cualquier cambio de esquema
nuevo se hace con una migración de Alembic (`alembic revision`), no
editando schema.sql a mano con ALTER TABLE ... IF NOT EXISTS.

Instalaciones YA EXISTENTES (que ya tienen las tablas, creadas antes de
adoptar Alembic) no deben ejecutar este upgrade() de cero — deben
marcarse como ya aplicadas con:
    alembic stamp head
Instalaciones NUEVAS sí ejecutan esto de cero con `alembic upgrade head`.
"""
import os
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '2a9187c48a69'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA_SQL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "schema.sql")


def upgrade() -> None:
    """Crea el esquema núcleo completo (tasks, audit_log, rag_chunks, documents,
    collections, projects, project_settings, project_members, evaluations,
    n8n_integrations), leyendo directamente db/schema.sql."""
    with open(_SCHEMA_SQL_PATH, encoding="utf-8") as f:
        op.execute(f.read())


def downgrade() -> None:
    """Elimina TODO el esquema núcleo. Destructivo a propósito — es la
    baseline; no hay un estado anterior al que volver."""
    op.execute("""
        DROP TABLE IF EXISTS evaluations CASCADE;
        DROP TABLE IF EXISTS project_members CASCADE;
        DROP TABLE IF EXISTS n8n_integrations CASCADE;
        DROP TABLE IF EXISTS documents CASCADE;
        DROP TABLE IF EXISTS collections CASCADE;
        DROP TABLE IF EXISTS rag_chunks CASCADE;
        DROP TABLE IF EXISTS audit_log CASCADE;
        DROP TABLE IF EXISTS tasks CASCADE;
        DROP TABLE IF EXISTS project_settings CASCADE;
        DROP TABLE IF EXISTS projects CASCADE;
    """)

