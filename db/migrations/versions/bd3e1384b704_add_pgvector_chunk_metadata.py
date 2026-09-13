"""add pgvector chunk metadata

Revision ID: bd3e1384b704
Revises: 53330cf3f9ac
Create Date: 2026-09-13 11:13:08.793647
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "bd3e1384b704"
down_revision: Union[str, Sequence[str], None] = "53330cf3f9ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pgvector_table_exists() -> bool:
    bind = op.get_bind()
    result = bind.exec_driver_sql(
        "SELECT to_regclass('public.rag_chunks_pgvector')"
    ).scalar()
    return result is not None


def upgrade() -> None:
    if not _pgvector_table_exists():
        return

    op.execute("""
        ALTER TABLE rag_chunks_pgvector
        ADD COLUMN IF NOT EXISTS page_number INTEGER
    """)
    op.execute("""
        ALTER TABLE rag_chunks_pgvector
        ADD COLUMN IF NOT EXISTS section TEXT
    """)
    op.execute("""
        ALTER TABLE rag_chunks_pgvector
        ADD COLUMN IF NOT EXISTS char_start INTEGER
    """)
    op.execute("""
        ALTER TABLE rag_chunks_pgvector
        ADD COLUMN IF NOT EXISTS char_end INTEGER
    """)


def downgrade() -> None:
    if not _pgvector_table_exists():
        return

    op.execute("""
        ALTER TABLE rag_chunks_pgvector
        DROP COLUMN IF EXISTS char_end
    """)
    op.execute("""
        ALTER TABLE rag_chunks_pgvector
        DROP COLUMN IF EXISTS char_start
    """)
    op.execute("""
        ALTER TABLE rag_chunks_pgvector
        DROP COLUMN IF EXISTS section
    """)
    op.execute("""
        ALTER TABLE rag_chunks_pgvector
        DROP COLUMN IF EXISTS page_number
    """)
