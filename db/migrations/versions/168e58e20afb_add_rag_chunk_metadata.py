"""add rag chunk metadata

Revision ID: 168e58e20afb
Revises: 7b9d1e4a2c10
Create Date: 2026-09-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "168e58e20afb"
down_revision: Union[str, None] = "7b9d1e4a2c10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rag_chunks",
        sa.Column("page_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "rag_chunks",
        sa.Column("section", sa.Text(), nullable=True),
    )
    op.add_column(
        "rag_chunks",
        sa.Column("char_start", sa.Integer(), nullable=True),
    )
    op.add_column(
        "rag_chunks",
        sa.Column("char_end", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rag_chunks", "char_end")
    op.drop_column("rag_chunks", "char_start")
    op.drop_column("rag_chunks", "section")
    op.drop_column("rag_chunks", "page_number")
