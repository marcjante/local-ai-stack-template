"""Add optional per-team administrator tokens."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6f2a9b4c7e1"
down_revision: Union[str, None] = "c4e8a1f2b6d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("team", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("admin_token", sa.String(length=255), nullable=True))
        batch_op.create_index("ix_team_admin_token", ["admin_token"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("team", recreate="always") as batch_op:
        batch_op.drop_index("ix_team_admin_token")
        batch_op.drop_column("admin_token")
