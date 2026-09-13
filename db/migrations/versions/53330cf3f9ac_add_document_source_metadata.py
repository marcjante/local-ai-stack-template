"""add document source metadata

Revision ID: 53330cf3f9ac
Revises: 168e58e20afb
Create Date: 2026-09-12 21:56:11.123298
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "53330cf3f9ac"
down_revision: Union[str, Sequence[str], None] = "168e58e20afb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "documents",
        "source_metadata",
    )
