"""store the reason when a player cannot attend."""

from alembic import op
import sqlalchemy as sa


revision = "3d2f7e0a1c4b"
down_revision = "621920b0243a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attendance", sa.Column("absence_reason", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("attendance", "absence_reason")
