"""ejemplo: añade columna notes a projects

Revision ID: ed4c953f47f2
Revises: 2a9187c48a69
Create Date: 2026-09-07 11:51:03.379281

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ed4c953f47f2'
down_revision: Union[str, Sequence[str], None] = '2a9187c48a69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "notes")
